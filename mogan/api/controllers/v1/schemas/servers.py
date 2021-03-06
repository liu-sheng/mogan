# Copyright 2017 Huawei Technologies Co.,LTD.
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


from mogan.api.validation import parameter_types

create_server = {
    "type": "object",
    "properties": {
        "server": {
            "type": "object",
            "properties": {
                'name': parameter_types.name,
                'description': parameter_types.description,
                'availability_zone': parameter_types.availability_zone,
                'image_uuid': parameter_types.image_id,
                'flavor_uuid': parameter_types.flavor_id,
                'networks': {
                    'type': 'array', 'minItems': 1,
                    'items': {
                        'type': 'object',
                        'properties': {
                            'net_id': parameter_types.network_id,
                            'port_id': parameter_types.network_port_id,
                        },
                        'oneOf': [
                            {'required': ['net_id']},
                            {'required': ['port_id']}
                        ],
                    },
                    'additionalProperties': False,
                },
                'user_data': {'type': 'string', 'format': 'base64'},
                'personality': parameter_types.personality,
                'key_name': parameter_types.name,
                'min_count': {'type': 'integer', 'minimum': 1},
                'max_count': {'type': 'integer', 'minimum': 1},
                'metadata': parameter_types.metadata,
                'partitions': {
                    'type': 'object',
                    'properties': {
                        'root_gb': parameter_types.positive_integer,
                        'ephemeral_gb': parameter_types.non_negative_integer,
                        'swap_mb': parameter_types.non_negative_integer,
                    },
                    'required': ['root_gb'],
                    'additionalProperties': False,
                },
            },
            'required': ['name', 'image_uuid', 'flavor_uuid', 'networks'],
            'additionalProperties': False,
        },
        'scheduler_hints': {
            'type': 'object',
            'properties': {
                'group': parameter_types.server_group_id
            },
            'additionalProperties': False,
        },
    },
    'required': ['server'],
    'additionalProperties': False,
}
