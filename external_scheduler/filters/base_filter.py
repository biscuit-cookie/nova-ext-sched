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

class BaseExternalFilter(object):
    """Base class for host external filters."""

    def before_filtering(self, filter_obj_list, spec_obj):
        """Method called once by nova ExternalFilter before filtering operations begin
        We usually use it to do a single request to the monitoring stack for all objects

        :param filter_obj_list: hoststate list
        :param spec_obj: filter options
        :return: None
        """
        pass

    def filter_one(self, host_state, spec_obj):
        """Return True if current host CPU usage is adequate for a new deployment

        :param host_state: nova.scheduler.host_manager.HostState
        :param spec_obj: filter options
        :return: boolean
        """
        return True