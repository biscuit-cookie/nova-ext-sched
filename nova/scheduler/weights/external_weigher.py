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

from oslo_log import log as logging
from stevedore import driver

from nova.scheduler import weights

import nova.conf
CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

class ExternalWeigher(weights.BaseHostWeigher):

    def __init__(self):
        # Load the external weighter dynamically using stevedore
        self.mgr = driver.DriverManager(
            namespace="nova.scheduler.external_scheduler",
            name="external_scheduler",
            invoke_on_load=True,
            invoke_args=(LOG,) # pass the logger, must be a tuple, the ',' is important
        )

    def weigh_objects(self, weighed_obj_list, weight_properties):
        """Override weigh_objects from BaseWeigher to implement a hook
        """
        LOG.debug(f"ExternalWeigher: weigh_objects called")
        self.mgr.driver.before_weighting(weighed_obj_list, weight_properties) # the hook
        return super().weigh_objects(weighed_obj_list, weight_properties)

    def _weigh_object(self, host_state, weight_properties):
        """Weight a given host
        """
        LOG.debug(f"ExternalWeigher: _weigh_object called")
        return self.mgr.driver.weight_one(host_state, weight_properties) # let the decision to external plugin