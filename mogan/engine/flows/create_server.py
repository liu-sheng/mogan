# Copyright 2016 Huawei Technologies Co.,LTD.
# All Rights Reserved.

#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import base64
import gzip
import shutil
import tempfile
import traceback

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
import six
import taskflow.engines
from taskflow.patterns import linear_flow

from mogan.common import exception
from mogan.common import flow_utils
from mogan.common.i18n import _
from mogan.common import utils
from mogan.engine import configdrive
from mogan.engine import metadata as server_metadata
from mogan import objects

LOG = logging.getLogger(__name__)

ACTION = 'server:create'
CONF = cfg.CONF


class OnFailureRescheduleTask(flow_utils.MoganTask):
    """Triggers a rescheduling request to be sent when reverting occurs.

    If rescheduling doesn't occur this task errors out the server.
    """

    def __init__(self, engine_rpcapi):
        requires = ['filter_properties', 'request_spec', 'server',
                    'requested_networks', 'user_data', 'injected_files',
                    'key_pair', 'partitions', 'context']
        super(OnFailureRescheduleTask, self).__init__(addons=[ACTION],
                                                      requires=requires)
        self.engine_rpcapi = engine_rpcapi
        # These exception types will trigger the server to be set into error
        # status rather than being rescheduled.
        self.no_reschedule_exc_types = [
            # The server has been removed from the database, that can not
            # be fixed by rescheduling.
            exception.ServerNotFound,
            exception.ServerDeployAborted,
            exception.NetworkError,
        ]

    def execute(self, **kwargs):
        pass

    def _reschedule(self, context, cause, request_spec, filter_properties,
                    server, requested_networks, user_data, injected_files,
                    key_pair, partitions):
        """Actions that happen during the rescheduling attempt occur here."""

        create_server = self.engine_rpcapi.schedule_and_create_servers

        if not filter_properties:
            filter_properties = {}
        if 'retry' not in filter_properties:
            filter_properties['retry'] = {}

        retry_info = filter_properties['retry']
        num_attempts = retry_info.get('num_attempts', 0)

        LOG.debug("Server %(server_id)s: re-scheduling %(method)s "
                  "attempt %(num)d due to %(reason)s",
                  {'server_id': server.uuid,
                   'method': utils.make_pretty_name(create_server),
                   'num': num_attempts,
                   'reason': cause.exception_str})

        if all(cause.exc_info):
            # Stringify to avoid circular ref problem in json serialization
            retry_info['exc'] = traceback.format_exception(*cause.exc_info)

        return create_server(context, [server], requested_networks,
                             user_data=user_data,
                             injected_files=injected_files,
                             key_pair=key_pair,
                             partitions=partitions,
                             request_spec=request_spec,
                             filter_properties=filter_properties)

    def revert(self, context, result, flow_failures, server, **kwargs):
        # Clean up associated node
        server.node_uuid = None
        server.node = None
        server.save()

        # Check if we have a cause which can tell us not to reschedule and
        # set the server's status to error.
        for failure in flow_failures.values():
            if failure.check(*self.no_reschedule_exc_types):
                LOG.error("Server %s: create failed and no reschedule.",
                          server.uuid)
                return False

        cause = list(flow_failures.values())[0]
        try:
            self._reschedule(context, cause, server=server, **kwargs)
            return True
        except exception.MoganException:
            LOG.exception("Server %s: rescheduling failed",
                          server.uuid)

        return False


class BuildNetworkTask(flow_utils.MoganTask):
    """Build network for the server."""

    def __init__(self, manager):
        requires = ['server', 'requested_networks', 'context']
        super(BuildNetworkTask, self).__init__(addons=[ACTION],
                                               requires=requires)
        self.manager = manager

    def _build_networks(self, context, server, requested_networks):
        ports = self.manager.driver.get_portgroups_and_ports(server.node_uuid)
        if len(requested_networks) > len(ports):
            raise exception.InterfacePlugException(_(
                "Ironic node: %(id)s virtual to physical interface count"
                "  mismatch"
                " (Vif count: %(vif_count)d, Pif count: %(pif_count)d)")
                % {'id': server.node_uuid,
                   'vif_count': len(requested_networks),
                   'pif_count': len(ports)})

        nics_obj = objects.ServerNics(context)

        for vif in requested_networks:
            try:
                if vif.get('net_id'):
                    port = self.manager.network_api.create_port(
                        context, vif['net_id'], server.uuid)
                    preserve_on_delete = False
                elif vif.get('port_id'):
                    port = self.manager.network_api.show_port(
                        context, vif.get('port_id'))
                    self.manager.network_api.check_port_availability(port)
                    self.manager.network_api.bind_port(context,
                                                       port['id'],
                                                       server)
                    preserve_on_delete = True

                nic_dict = {'port_id': port['id'],
                            'network_id': port['network_id'],
                            'mac_address': port['mac_address'],
                            'fixed_ips': port['fixed_ips'],
                            'preserve_on_delete': preserve_on_delete,
                            'server_uuid': server.uuid}

                server_nic = objects.ServerNic(context, **nic_dict)
                nics_obj.objects.append(server_nic)

                self.manager.driver.plug_vif(server.node_uuid,
                                             port['id'])
                # Get updated VIF info
                port_dict = self.manager.network_api.show_port(
                    context, port.get('id'))

                # Update the real physical mac address from ironic.
                server_nic.mac_address = port_dict['mac_address']
            except Exception as e:
                # Set nics here, so we can clean up the
                # created networks during reverting.
                server.nics = nics_obj
                LOG.error("Server %(server)s: create or get network "
                          "failed. The reason is %(reason)s",
                          {"server": server.uuid, "reason": e})
                raise exception.NetworkError(_(
                    "Build network for server failed."))

        return nics_obj

    def execute(self, context, server, requested_networks):
        server_nics = self._build_networks(
            context,
            server,
            requested_networks)

        server.nics = server_nics
        server.save()

    def revert(self, context, result, flow_failures, server, **kwargs):
        # Check if we need to clean up networks.
        if server.nics:
            LOG.debug("Server %s: cleaning up node networks",
                      server.uuid)
            self.manager.destroy_networks(context, server)
            # Unset nics here as we have destroyed it.
            server.nics = None
            return True

        return False


class GenerateConfigDriveTask(flow_utils.MoganTask):
    """Generate ConfigDrive value the server."""

    def __init__(self):
        requires = ['server', 'user_data', 'injected_files', 'key_pair',
                    'configdrive', 'context']
        super(GenerateConfigDriveTask, self).__init__(addons=[ACTION],
                                                      requires=requires)

    def _generate_configdrive(self, context, server, user_data=None,
                              files=None, key_pair=None):
        """Generate a config drive."""

        i_meta = server_metadata.ServerMetadata(
            server, content=files, user_data=user_data, key_pair=key_pair)
        with tempfile.NamedTemporaryFile() as uncompressed:
            with configdrive.ConfigDriveBuilder(server_md=i_meta) as cdb:
                cdb.make_drive(uncompressed.name)

            with tempfile.NamedTemporaryFile() as compressed:
                # compress config drive
                with gzip.GzipFile(fileobj=compressed, mode='wb') as gzipped:
                    uncompressed.seek(0)
                    shutil.copyfileobj(uncompressed, gzipped)

                # base64 encode config drive
                compressed.seek(0)
                return base64.b64encode(compressed.read())

    def execute(self, context, server, user_data, injected_files, key_pair,
                configdrive):

        try:
            configdrive['value'] = self._generate_configdrive(
                context, server, user_data=user_data, files=injected_files,
                key_pair=key_pair)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                msg = ("Failed to build configdrive: %s" %
                       six.text_type(e))
                LOG.error(msg, server=server)

        LOG.info("Config drive for server %(server)s created.",
                 {'server': server.uuid})


class CreateServerTask(flow_utils.MoganTask):
    """Build and deploy the server."""

    def __init__(self, driver):
        requires = ['server', 'configdrive', 'context']
        super(CreateServerTask, self).__init__(addons=[ACTION],
                                               requires=requires)
        self.driver = driver

    def execute(self, context, server, configdrive, partitions):
        configdrive_value = configdrive.get('value')
        self.driver.spawn(context, server, configdrive_value, partitions)
        LOG.info('Successfully provisioned Ironic node %s',
                 server.node_uuid)

    def revert(self, context, result, flow_failures, server, **kwargs):
        LOG.debug("Server %s: destroy backend node", server.uuid)
        self.driver.destroy(context, server)
        return True


def get_flow(context, manager, server, requested_networks, user_data,
             injected_files, key_pair, partitions, request_spec,
             filter_properties):

    """Constructs and returns the manager entrypoint flow

    This flow will do the following:

    1. Build networks for the server and set port id back to baremetal port
    2. Generate configdrive value for server.
    3. Do node deploy and handle errors.
    4. Reschedule if the tasks are on failure.
    """

    flow_name = ACTION.replace(":", "_") + "_manager"
    server_flow = linear_flow.Flow(flow_name)

    # This injects the initial starting flow values into the workflow so that
    # the dependency order of the tasks provides/requires can be correctly
    # determined.
    create_what = {
        'context': context,
        'filter_properties': filter_properties,
        'request_spec': request_spec,
        'server': server,
        'requested_networks': requested_networks,
        'user_data': user_data,
        'injected_files': injected_files,
        'key_pair': key_pair,
        'partitions': partitions,
        'configdrive': {}
    }

    server_flow.add(OnFailureRescheduleTask(manager.engine_rpcapi),
                    BuildNetworkTask(manager),
                    GenerateConfigDriveTask(),
                    CreateServerTask(manager.driver))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(server_flow, store=create_what)
