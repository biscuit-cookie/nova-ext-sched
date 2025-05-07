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

from . import BaseExternalWeigher

class CpuLoadWeight(BaseExternalWeigher):

    def __init__(self, logger, config, monitoring):
        self.LOG           = logger
        self.sigma         = config.getfloat("cpu_load", "degree", fallback=1.65) # z-score
        self.load_target   = config.getfloat("cpu_load", "load", fallback=0.85)
        self.exclude_alloc = config.getfloat("cpu_load", "exclude_alloc", fallback=0.8)
        self.monitoring    = monitoring
        self.multiplier    = 1

    def before_weighting(self, weighed_obj_list, weight_properties):
        """Method called once by nova ExternalWeighter before weighting operations begin
        We use it to do a single request to the monitoring stack for all objects

        :param weighed_obj_list: hoststate list
        :param weight_properties: weight options
        :return: None
        """
        self.LOG.debug(f"nova-ext-sched[cpuloadweight]: weight_all called")
        # Only retrieve data for effectively oversubscribed hosts, the others should be considered neutral
        regex_host = '|'.join([host.obj.host for host in weighed_obj_list if (host.obj.vcpus_used > ( host.obj.vcpus_total * self.exclude_alloc ))])
        metrics = self.get_hosts_metric(regex_host=regex_host)
        for obj in weighed_obj_list:
            if obj.obj.host in metrics: setattr(obj, 'ext-sched.idle-ratio', metrics[obj.obj.host])

    def weight_one(self, host_state, weight_properties):
        """Return a score to elect the server as suitable (higher weight wins)
           We want spreading to be the default for effectively oversubscribed host (those where vCPUs > CPU)
           This is done by scoring by the amount of free res. For non-filled host, usage is not retrieved from prom and we return 0

        :param host_state: nova.scheduler.host_manager.HostState
        :param weight_properties: weight options
        :return: score
        """
        self.LOG.debug(f"nova-ext-sched[cpuloadweight]: weight_one called")
        if not hasattr(host_state, 'ext-sched.idle-ratio'):
            self.LOG.debug(f"nova-ext-sched[cpuloadweight]: no prediction retrieved from the monitoring stack for {host_state.host}, will use default value")
            return 0 # if not set, we return a neutral value

        idle_ratio = getattr(host_state, 'ext-sched.idle-ratio')
        vcpus_free = int((self.load_target - (1 - idle_ratio)) * host_state.vcpus_total) # estimate based on targeted load and current usage
        vcpus_free = min(max(0, vcpus_free), host_state.vcpus_total) # Cap the result under specific bounds to avoid interfering with other weighers

        self.LOG.debug(f"nova-ext-sched[cpuloadweight]: weight_one {host_state.nodename} predicted idle min: {idle_ratio}, vcpu free: {vcpus_free}")
        return vcpus_free * self.multiplier

    ##################################################
    # Implement logic                                #
    ##################################################
    def get_hosts_metric(self, regex_host : str, degree : str = None):
        """Retrieve data from prometheus related to the node-exporter (cpu-time) and compute an estimate of next min usage

        :param regex_host: string of host list as regex. E.g., host1|host2|host3
        :param degree: conservative degree of oversubscription policy
        :return: dict of host:float
        """
        sigma = self.sigma if degree is None else degree

        # This formula captures unused CPU resources (mode = "idle") over a time window.
        # We are interested in usage peaks — i.e., the moments with the lowest idle rate — which is why we use the 1st percentile (q01) of idle.
        # To account for variability (assuming a Gaussian-like distribution), we subtract N standard deviations from the q01 value, tightening the estimate toward worst-case usage.
        # The avg(rate(...)) by (instance) aggregates per-core idle rates into a single host-level idle ratio.

        query = 'rec_host_cpu_idle_q01{instance=~"' + regex_host + '"} - ' + str(sigma) + ' * rec_host_cpu_idle_std{instance=~"' + regex_host + '"}'
        return self.monitoring.query(query)
