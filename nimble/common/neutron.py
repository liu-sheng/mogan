# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from neutronclient.v2_0 import client as clientv20
from oslo_log import log as logging

from nimble.common import keystone
from nimble.conf import CONF

LOG = logging.getLogger(__name__)

_NEUTRON_SESSION = None


def _get_neutron_session():
    global _NEUTRON_SESSION
    if not _NEUTRON_SESSION:
        _NEUTRON_SESSION = keystone.get_session('neutron')
    return _NEUTRON_SESSION


def get_client(token=None):
    params = {'retries': CONF.neutron.retries}
    url = CONF.neutron.url
    session = _get_neutron_session()
    if token is None:
        params['session'] = session
        # NOTE(pas-ha) endpoint_override==None will auto-discover
        # endpoint from Keystone catalog.
        # Region is needed only in this case.
        # SSL related options are ignored as they are already embedded
        # in keystoneauth Session object
        if url:
            params['endpoint_override'] = url
        else:
            params['region_name'] = CONF.keystone.region_name
    else:
        params['token'] = token
        params['endpoint_url'] = url or keystone.get_service_url(
            session, service_type='network')
        params.update({
            'timeout': CONF.neutron.url_timeout,
            'insecure': CONF.neutron.insecure,
            'ca_cert': CONF.neutron.cafile})

    return clientv20.Client(**params)


def create_ports(context, network_uuid, macs):
    """Create neutron port."""

    client = get_client(context.auth_token)
    body = {
        'port': {
            'network_id': network_uuid,
            'mac_address': macs
        }
    }

    port = client.create_port(body)

    return port
