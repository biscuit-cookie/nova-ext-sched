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
"""
Plug additional filter/weigher to nova scheduling process

"""

import requests
import configparser
import os, random
from . import filters, weights

class ExternalScheduler():

    def __init__(self, logger):
        self.LOG    = logger
        self.config = configparser.ConfigParser()

        # Get the absolute path to the script's directory
        script_dir  = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "plugin.conf")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                self.config.read_file(f)
        else:
            self.LOG.warning(f"nova-ext-sched[global]: No configuration found, was expecting plugin.conf")

        self.monitoring  = PrometheusEndpoint(logger=logger, config=self.config)

        enabled_filters_label  = self.config.get("global", "enabled_filters", fallback="").split(",")
        enabled_weighers_label = self.config.get("global", "enabled_weighers", fallback="").split(",")

        filter_unknown = [name for name in enabled_filters_label if name and not hasattr(filters, name)]
        if filter_unknown: self.LOG.warning(f"nova-ext-sched[global]: following external filters could not be found {filter_unknown}")
        weigher_unknown = [name for name in enabled_weighers_label if name and not hasattr(weights, name)]
        if weigher_unknown: self.LOG.warning(f"nova-ext-sched[global]: following external weighers could not be found {weigher_unknown}")

        self.filter_list = [getattr(filters, name)(logger=logger, config=self.config, monitoring=self.monitoring) for name in enabled_filters_label if name and hasattr(filters, name)]
        self.weight_list = [getattr(weights, name)(logger=logger, config=self.config, monitoring=self.monitoring) for name in enabled_weighers_label if name and hasattr(weights, name)]

        if not self.filter_list: self.LOG.warning(f"nova-ext-sched[global]: No external filters specified")
        if not self.weight_list: self.LOG.warning(f"nova-ext-sched[global]: No external weighers specified")


    def before_filtering(self, filter_obj_list, spec_obj):
        """Method called once by nova ExternalFilter before filtering operations begin
        We use it to let the opportunity to do a single request to the monitoring stack for all objects 

        :param filter_obj_list: hoststate list
        :param spec_obj: filter options
        :return: None
        """
        for filter in self.filter_list:
            try:
                filter.before_filtering(filter_obj_list, spec_obj)
            except Exception as e:
                self.LOG.warning(f"nova-ext-sched[global]: Error in filter {filter.__class__.__name__} during before_filtering: {e}")

    def filter_one(self, host_state, spec_obj):
        """Return True if current host is adequate for a new deployment

        :param host_state: nova.scheduler.host_manager.HostState
        :param spec_obj: filter options
        :return: boolean
        """
        for filter in self.filter_list:
            try:
                if not filter.filter_one(host_state, spec_obj):
                    return False
            except Exception as e:
                self.LOG.warning(f"nova-ext-sched[global]: Error in filter {filter.__class__.__name__} during filter_one: {e}")
        return True

    def before_weighting(self, weighed_obj_list, weight_properties):
        """Method called once by nova ExternalWeigher before weighting operations begin
        We use it to let the opportunity to do a single request to the monitoring stack for all object

        :param filter_obj_list: hoststate list
        :param spec_obj: filter options
        :return: None
        """
        for weight in self.weight_list:
            try:
                weight.before_weighting(weighed_obj_list, weight_properties)
            except Exception as e:
                self.LOG.warning(f"nova-ext-sched[global]: Error in weigher {filter.__class__.__name__} during before_weighting: {e}")

    def weight_one(self, host_state, weight_properties):
        """Return a score to elect the server as suitable (higher weight wins)

        :param host_state: nova.scheduler.host_manager.HostState
        :param weight_properties: weight options
        :return: score
        """
        score = 0
        for weigher in self.weight_list:
            try:
                score += weigher.weight_one(host_state, weight_properties)
            except Exception as e:
                self.LOG.warning(f"nova-ext-sched[global]: Error in weigher {filter.__class__.__name__} during weight_one: {e}")
        return score

class PrometheusEndpoint(object):

    def __init__(self, logger, config):
        self.LOG      = logger

        endpoint_raw  = config.get("prometheus", "endpoint", fallback="http://localhost:9090/api/v1/query")
        self.endpoint = endpoint_raw if ',' not in endpoint_raw else endpoint_raw.split(',')
        self.timeout  = config.getfloat("prometheus", "timeout", fallback=5) # in seconds

    def query(self, query, endpoint : str = None, timeout : int = None):
        """Query Prometheus and return the response with a timeout."""
        endpoint = self.get_endpoint() if endpoint is None else endpoint
        timeout  = self.timeout if timeout is None else timeout
        try:
            response = requests.get(
                f"{endpoint}",
                params={"query": query},
                timeout=timeout  # Timeout in seconds
            )
            response.raise_for_status()  # Raise an error for HTTP failures

            # Format answer
            result = {}
            for metric in response.json()["data"]["result"]:
                instance = metric["metric"]["instance"]
                value = metric["value"][1]  # The result
                result[instance] = float(value)
            return result

        except requests.exceptions.Timeout:
            self.LOG.error(f"nova-ext-sched[prometheus]: request time-out with {endpoint} (limit is {timeout}s)")
        except requests.exceptions.RequestException as e:
            self.LOG.error(f"nova-ext-sched[prometheus]: error querying {endpoint} : {e}")
        except Exception as e:
            self.LOG.error(f"nova-ext-sched[prometheus]: error in plugin with endpoint {endpoint} : {e}")
        return {}

    def get_endpoint(self):
        """Return a random prometheus endpoint to spread the load"""
        if type(self.endpoint) is list:
            return random.choice(self.endpoint)
        return self.endpoint
