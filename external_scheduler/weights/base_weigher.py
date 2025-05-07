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

class BaseExternalWeigher(object):
    """Base class for host external weighers."""

    def before_weighting(self, weighed_obj_list, weight_properties):
        """Method called once by nova ExternalWeighter before weighting operations begin
        We use it to do a single request to the monitoring stack for all objects

        :param filter_obj_list: hoststate list
        :param spec_obj: filter options
        :return: None
        """
        pass

    def weight_one(self, host_state, weight_properties):
        """Return a score to elect the server as suitable (higher weight wins)

        :param host_state: nova.scheduler.host_manager.HostState
        :param weight_properties: weight options
        :return: score
        """
        return 0