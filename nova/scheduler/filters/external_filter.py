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

from nova.scheduler import filters

import nova.conf
CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

class ExternalFilter(filters.BaseHostFilter):

    def __init__(self):
        # Load the external filter dynamically using stevedore
        self.mgr = driver.DriverManager(
            namespace="nova.scheduler.external_scheduler",
            name="external_scheduler",
            invoke_on_load=True,
            invoke_args=(LOG,) # pass the logger, must be a tuple, the ',' is important
        )

    def filter_all(self, filter_obj_list, spec_obj):
        """Override filter_all from BaseFilter to implement a hook
        """
        LOG.debug(f"ExternalFilter: filter_all called")
        self.mgr.driver.before_filtering(filter_obj_list, spec_obj) # the hook
        for obj in filter_obj_list:
            if self._filter_one(obj, spec_obj):
                yield obj

    def host_passes(self, host_state, spec_obj):
        """Filter a given host
        """
        LOG.debug(f"ExternalFilter: host_passes called")
        return self.mgr.driver.filter_one(host_state, spec_obj) # let the decision to external plugin
