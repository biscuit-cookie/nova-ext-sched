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

from . import BaseExternalFilter

class CpuLoadFilter(BaseExternalFilter):

    def __init__(self, logger, config, monitoring):
        self.LOG           = logger
        self.sigma         = config.getfloat("cpu_load", "degree", fallback=1.65)
        self.load_target   = config.getfloat("cpu_load", "load", fallback=0.8)
        self.exclude_alloc = config.getfloat("cpu_load", "exclude_alloc", fallback=0.8)
        self.monitoring    = monitoring

    def before_filtering(self, filter_obj_list, spec_obj):
        """Method called once by nova ExternalFilter before filtering operations begin
        We use it to do a single request to the monitoring stack for all objects

        :param filter_obj_list: hoststate list
        :param spec_obj: filter options
        :return: None
        """
        # Method called once before filtering to potentially do a single request to a monitoring stack for all objects
        self.LOG.debug(f"nova-ext-sched[cpuloadfilter]: before_filtering called")
        # Only retrieve data for effectively oversubscribed hosts, the others should be considered as passing the load test
        regex_host = '|'.join([host.nodename for host in filter_obj_list if (host.vcpus_used > ( host.vcpus_total * self.exclude_alloc ))])
        metrics = self.get_hosts_metric(regex_host=regex_host)
        for obj in filter_obj_list:
            if obj.nodename in metrics: setattr(obj, 'ext-sched.idle-ratio', metrics[obj.nodename])

    def filter_one(self, host_state, spec_obj):
        """Return True if current host CPU usage is adequate for a new deployment
           The CPU usage is analyzed through Prometheus

        :param host_state: nova.scheduler.host_manager.HostState
        :param spec_obj: filter options
        :return: boolean
        """
        self.LOG.debug(f"nova-ext-sched[cpuloadfilter]: filter_one called")
        if not hasattr(host_state, 'ext-sched.idle-ratio'):
            self.LOG.debug(f"nova-ext-sched[cpuloadfilter]: no prediction retrieved from the monitoring stack for {host_state.nodename}, will use default value")

        idle_ratio     = getattr(host_state, 'ext-sched.idle-ratio', 1.0) # if not set, we assume idle to not block scheduling when the monitoring stack is down
        vcpus_free     = int((self.load_target - (1 - idle_ratio)) * host_state.vcpus_total) # estimate based on targeted load and current usage
        instance_vcpus = spec_obj.vcpus

        self.LOG.debug(f"nova-ext-sched[cpuloadfilter]: filter_one {host_state.nodename} predicted idle min: {idle_ratio}, vcpu free: {vcpus_free}, request: {instance_vcpus}")
        if instance_vcpus <= vcpus_free:
            return True
        return False

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
