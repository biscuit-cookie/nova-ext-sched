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
Plug profile-based external filters/weighers to nova scheduling process

"""

import requests
import configparser
import os, random, threading

from stevedore import extension


FILTER_NAMESPACE  = "nova.scheduler.external_scheduler.filters"
WEIGHER_NAMESPACE = "nova.scheduler.external_scheduler.weighers"
CONFIG_ENV_VAR    = "NOVA_EXT_SCHED_CONFIG"


class ExternalScheduler():

    def __init__(self, logger):
        self.LOG         = logger
        self.config_path = self._get_config_path()
        self.lock        = threading.Lock() # Serialize hot-reload only; scheduling uses state snapshots
        self.state       = self._empty_state() # Last valid config/plugins snapshot

        try:
            self.state = self._load_config()
        except Exception as e:
            self.LOG.error(f"nova-ext-sched[global]: Failed to load configuration: {e}")

    def filter_all(self, filter_obj_list, spec_obj):
        """Filter a full HostState list with the profile selected for this request

        :param filter_obj_list: hoststate list
        :param spec_obj: filter options
        :return: hoststate list
        """
        state        = self._get_state()
        profile_name = self._get_profile_name(state, spec_obj)
        filter_list  = self._new_filters(state, profile_name)
        if filter_list is None:
            self.LOG.warning(f"nova-ext-sched[global]: Unknown profile {profile_name}, rejecting all hosts")
            return []

        for ext_filter in filter_list:
            try:
                ext_filter.before_filtering(filter_obj_list, spec_obj)
            except Exception as e:
                self.LOG.warning(f"nova-ext-sched[global]: Error in filter {ext_filter.__class__.__name__} during before_filtering: {e}")

        return [
            host_state for host_state in filter_obj_list
            if self._filter_one(filter_list, host_state, spec_obj)
        ]

    def weigh_all(self, weighed_obj_list, weight_properties):
        """Return raw external weights for a full WeighedHost list

        :param weighed_obj_list: weighed host list
        :param weight_properties: weight options
        :return: score list
        """
        state        = self._get_state()
        profile_name = self._get_profile_name(state, weight_properties)
        weight_list  = self._new_weighers(state, profile_name)
        if weight_list is None:
            self.LOG.warning(f"nova-ext-sched[global]: Unknown profile {profile_name}, returning neutral weights")
            return [0 for _obj in weighed_obj_list]

        for weight in weight_list:
            try:
                weight.before_weighting(weighed_obj_list, weight_properties)
            except Exception as e:
                self.LOG.warning(f"nova-ext-sched[global]: Error in weigher {weight.__class__.__name__} during before_weighting: {e}")

        return [
            self._weight_one(weight_list, weighed_obj.obj, weight_properties)
            for weighed_obj in weighed_obj_list
        ]

    def filter_one(self, host_state, spec_obj):
        """Return True if current host is adequate for a new deployment

        :param host_state: nova.scheduler.host_manager.HostState
        :param spec_obj: filter options
        :return: boolean
        """
        state        = self._get_state()
        profile_name = self._get_profile_name(state, spec_obj)
        filter_list  = self._new_filters(state, profile_name)
        if filter_list is None:
            self.LOG.warning(f"nova-ext-sched[global]: Unknown profile {profile_name}, rejecting host")
            return False
        return self._filter_one(filter_list, host_state, spec_obj)

    def weight_one(self, host_state, weight_properties):
        """Return a score to elect the server as suitable (higher weight wins)

        :param host_state: nova.scheduler.host_manager.HostState
        :param weight_properties: weight options
        :return: score
        """
        state        = self._get_state()
        profile_name = self._get_profile_name(state, weight_properties)
        weight_list  = self._new_weighers(state, profile_name)
        if weight_list is None:
            self.LOG.warning(f"nova-ext-sched[global]: Unknown profile {profile_name}, returning neutral weight")
            return 0
        return self._weight_one(weight_list, host_state, weight_properties)

    def _get_state(self):
        mtime = self._get_config_mtime()
        if mtime == self.state["mtime"]:
            return self.state

        # A request keeps its local state reference. A successful reload swaps
        # self.state only for requests that start after the swap.
        with self.lock:
            mtime = self._get_config_mtime()
            if mtime == self.state["mtime"]:
                return self.state
            try:
                self.state = self._load_config()
            except Exception as e:
                self.LOG.error(f"nova-ext-sched[global]: Failed to reload configuration from {self.config_path}: {e}")
        return self.state

    def _load_config(self):
        config = configparser.ConfigParser()
        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                config.read_file(f)
        else:
            self.LOG.warning(f"nova-ext-sched[global]: No configuration found, was expecting {self.config_path}")

        monitoring      = PrometheusEndpoint(logger=self.LOG, config=config)
        filter_classes  = self._load_plugins(FILTER_NAMESPACE)
        weigher_classes = self._load_plugins(WEIGHER_NAMESPACE)
        profiles        = self._read_profiles(config)

        default_profile = config.get("global", "default_profile", fallback="default").strip() or "default"
        profile_key     = config.get("global", "profile_hint_key", fallback="ext_sched_profile").strip() or "ext_sched_profile"
        unknown_policy  = config.get("global", "unknown_profile_policy", fallback="reject").strip().lower() or "reject"

        if unknown_policy not in ("reject", "default"):
            raise ValueError("unknown_profile_policy must be either 'reject' or 'default'")
        if default_profile not in profiles:
            raise ValueError(f"default_profile {default_profile} is not defined")

        self._check_plugins(profiles, filter_classes, weigher_classes)

        if not [name for profile in profiles.values() for name in profile["filters"]]:
            self.LOG.warning(f"nova-ext-sched[global]: No external filters specified")
        if not [name for profile in profiles.values() for name in profile["weighers"]]:
            self.LOG.warning(f"nova-ext-sched[global]: No external weighers specified")

        return {
            "mtime": self._get_config_mtime(),
            "config": config, 
            "monitoring": monitoring, 
            "profiles": profiles, # profile name -> {"filters": [...], "weighers": [...]}
            "filters": filter_classes, # stevedore name -> filter class
            "weighers": weigher_classes, # stevedore name -> weigher class
            "default_profile": default_profile,
            "profile_key": profile_key, # scheduler hint profile key
            "unknown_policy": unknown_policy, # policy for unknown profile
        }

    def _empty_state(self):
        config = configparser.ConfigParser()
        monitoring = PrometheusEndpoint(logger=self.LOG, config=config)
        return {
            "mtime": -2,
            "config": config,
            "monitoring": monitoring,
            "profiles": {"default": {"filters": [], "weighers": []}},
            "filters": {},
            "weighers": {},
            "default_profile": "default",
            "profile_key": "ext_sched_profile",
            "unknown_policy": "reject",
        }

    def _read_profiles(self, config):
        profile_sections = [
            section for section in config.sections()
            if section.startswith("profile:")
        ]

        if not profile_sections:
            return {
                "default": {
                    "filters": self._get_config_list(config, "global", "enabled_filters"),
                    "weighers": self._get_config_list(config, "global", "enabled_weighers"),
                }
            }

        profiles = {}
        for section in profile_sections:
            profile = section.split(":", 1)[1].strip()
            if not profile:
                raise ValueError("profile section name cannot be empty")
            profiles[profile] = {
                "filters": self._get_config_list(config, section, "filters"),
                "weighers": self._get_config_list(config, section, "weighers"),
            }
        return profiles

    def _check_plugins(self, profiles, filter_classes, weigher_classes):
        filter_names  = [name for profile in profiles.values() for name in profile["filters"]]
        weigher_names = [name for profile in profiles.values() for name in profile["weighers"]]

        filter_unknown = sorted(set([name for name in filter_names if name not in filter_classes]))
        if filter_unknown:
            raise ValueError(f"following external filters could not be found {filter_unknown}")

        weigher_unknown = sorted(set([name for name in weigher_names if name not in weigher_classes]))
        if weigher_unknown:
            raise ValueError(f"following external weighers could not be found {weigher_unknown}")

    def _get_profile_name(self, state, spec_obj):
        scheduler_hints = {}
        if isinstance(spec_obj, dict):
            scheduler_hints = spec_obj.get("scheduler_hints", {})
        else:
            scheduler_hints = getattr(spec_obj, "scheduler_hints", {}) or {}

        profile = None
        if isinstance(scheduler_hints, dict):
            profile = scheduler_hints.get(state["profile_key"])
            if isinstance(profile, (list, tuple)):
                profile = profile[0] if profile else None
            if isinstance(profile, str):
                profile = profile.strip()

        return profile or state["default_profile"]

    def _get_profile(self, state, profile_name):
        profile = state["profiles"].get(profile_name)
        if profile:
            return profile
        if state["unknown_policy"] == "default":
            return state["profiles"][state["default_profile"]]
        # None means the request asked for an unknown profile and the policy
        # is reject.
        return None

    def _new_filters(self, state, profile_name):
        profile = self._get_profile(state, profile_name)
        if profile is None:
            return None
        return self._new_plugins(profile["filters"], state["filters"], state)

    def _new_weighers(self, state, profile_name):
        profile = self._get_profile(state, profile_name)
        if profile is None:
            return None
        return self._new_plugins(profile["weighers"], state["weighers"], state)

    def _new_plugins(self, names, classes, state):
        plugins = []
        for name in names:
            try:
                plugins.append(classes[name](logger=self.LOG, config=state["config"], monitoring=state["monitoring"]))
            except Exception as e:
                self.LOG.warning(f"nova-ext-sched[global]: Could not instantiate plugin {name}: {e}")
        return plugins

    def _filter_one(self, filter_list, host_state, spec_obj):
        for ext_filter in filter_list:
            try:
                if not ext_filter.filter_one(host_state, spec_obj):
                    return False
            except Exception as e:
                self.LOG.warning(f"nova-ext-sched[global]: Error in filter {ext_filter.__class__.__name__} during filter_one: {e}")
        return True

    def _weight_one(self, weight_list, host_state, weight_properties):
        score = 0
        for weigher in weight_list:
            try:
                score += weigher.weight_one(host_state, weight_properties)
            except Exception as e:
                self.LOG.warning(f"nova-ext-sched[global]: Error in weigher {weigher.__class__.__name__} during weight_one: {e}")
        return score

    def _load_plugins(self, namespace):
        plugins = {}

        # Stevedore caches entry points. Drop this namespace before rebuilding
        # state so newly delivered plugin packages can be discovered.
        try:
            extension.ExtensionManager.ENTRY_POINT_CACHE.pop(namespace, None)
        except AttributeError:
            pass

        def on_load_failure(manager, entrypoint, exception):
            self.LOG.error(f"nova-ext-sched[global]: Could not load stevedore entry point {entrypoint.name} from {namespace}: {exception}")

        manager = extension.ExtensionManager(
            namespace=namespace,
            invoke_on_load=False,
            on_load_failure_callback=on_load_failure,
        )
        for ext in manager.extensions:
            if ext.name in plugins:
                self.LOG.warning(f"nova-ext-sched[global]: Duplicate stevedore entry point {ext.name} in {namespace}, using the last one")
            plugins[ext.name] = ext.plugin
        return plugins

    def _get_config_path(self):
        configured_path = os.environ.get(CONFIG_ENV_VAR)
        if configured_path:
            return configured_path

        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, "plugin.conf")

    def _get_config_mtime(self):
        try:
            return os.stat(self.config_path).st_mtime_ns
        except OSError:
            return -1

    def _get_config_list(self, config, section, option):
        value = config.get(section, option, fallback="")
        return [item.strip() for item in value.split(",") if item.strip()]


class PrometheusEndpoint(object):

    def __init__(self, logger, config):
        self.LOG      = logger

        endpoint_raw  = config.get("prometheus", "endpoint", fallback="http://localhost:9090/api/v1/query")
        self.endpoint = endpoint_raw if ',' not in endpoint_raw else [endpoint.strip() for endpoint in endpoint_raw.split(',')]
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
