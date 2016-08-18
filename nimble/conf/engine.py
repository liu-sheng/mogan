# Copyright 2016 Huawei Technologies Co.,LTD.
# All Rights Reserved.
#
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

from oslo_config import cfg

from nimble.common.i18n import _

opts = [
    cfg.IntOpt('workers_pool_size',
               default=100, min=2,
               help=_('The size of the workers greenthread pool. '
                      'Note that 1 threads will be reserved by the engine '
                      'itself for handling periodic tasks.')),
    cfg.StrOpt('api_url',
               help=_('URL of Nimble API service. If not set nimble can '
                      'get the current value from the keystone service '
                      'catalog.')),
    cfg.IntOpt('periodic_max_workers',
               default=8,
               help=_('Maximum number of worker threads that can be started '
                      'simultaneously by a periodic task. Should be less '
                      'than RPC thread pool size.')),
    cfg.IntOpt('sync_node_resource_interval',
               default=60,
               help=_('Interval between syncing the node resources from '
                      'ironic, in seconds.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='engine')