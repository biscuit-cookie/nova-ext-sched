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

from . import CpuLoadWeight
import time, statistics

class CpuLoadNoopWeight(CpuLoadWeight):

    """CpuLoadNoopWeight computes a weight based on CPU load but does not return it (No op version)
    """

    def before_weighting(self, weighed_obj_list, weight_properties):
        """Method called once by nova ExternalWeighter before weighting operations begin
        We use it to do a single request to the monitoring stack for all objects

        :param weighed_obj_list: hoststate list
        :param weight_properties: weight options
        :return: None
        """
        start = time.time()
        super().before_weighting(weighed_obj_list, weight_properties)
        duration = int( (time.time() - start) * 1000)
        parent = super()
        weight_list = [parent.weight_one(host.obj, weight_properties) for host in weighed_obj_list]
        weight_min, weight_max, weight_avg, weight_q50 = min(weight_list), max(weight_list), statistics.mean(weight_list), statistics.median(weight_list)
        self.LOG.info(f"nova-ext-sched[cpuloadnoopweight]: min|max|avg|q50|duration {weight_min}|{weight_max}|{weight_avg}|{weight_q50}|{duration}")

    def weight_one(self, host_state, weight_properties):
        """Return a score to elect the server as suitable (higher weight wins)
           We want spreading to be the default for effectively oversubscribed host (those where vCPUs > CPU)
           This is done by scoring by the amount of free res. For non-filled host, usage is not retrieved from prom and we return 0

        :param host_state: nova.scheduler.host_manager.HostState
        :param weight_properties: weight options
        :return: score
        """
        #super().weight_one(host_state, weight_properties)
        return 0
