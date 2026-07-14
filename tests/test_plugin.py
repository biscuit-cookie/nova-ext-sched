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

import os
import tempfile
import threading
import time
import unittest
import requests
from unittest.mock import MagicMock, patch

from external_scheduler import plugin


class Spec:
    def __init__(self, hints=None):
        self.scheduler_hints = hints or {}
        self.instance_uuid = "instance-uuid"


class Host:
    pass


class Weighed:
    def __init__(self, host):
        self.obj = host


class ExternalSchedulerTestCase(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.config_path = os.path.join(self.tempdir.name, "plugin.conf")
        self.mtime_ns = time.time_ns()
        self.filter_classes = {}
        self.weigher_classes = {}

        env_patch = patch.dict(
            os.environ,
            {plugin.CONFIG_ENV_VAR: self.config_path},
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)

        load_patch = patch.object(
            plugin.ExternalScheduler,
            "_load_plugins",
            side_effect=self._load_plugins,
        )
        load_patch.start()
        self.addCleanup(load_patch.stop)

    def _load_plugins(self, namespace):
        if namespace == plugin.FILTER_NAMESPACE:
            return dict(self.filter_classes)
        if namespace == plugin.WEIGHER_NAMESPACE:
            return dict(self.weigher_classes)
        return {}

    def write_config(self, body):
        with open(self.config_path, "w") as config_file:
            config_file.write(body)
        self.mtime_ns += 1000000000
        os.utime(self.config_path, ns=(self.mtime_ns, self.mtime_ns))

    def make_scheduler(self):
        return plugin.ExternalScheduler(logger=MagicMock())


class TestExternalSchedulerProfiles(ExternalSchedulerTestCase):

    def test_filter_profile_selected_from_scheduler_hints(self):
        calls = []

        class DefaultFilter:
            def __init__(self, logger, config, monitoring):
                pass

            def before_filtering(self, hosts, spec):
                calls.append(("before", "default"))

            def filter_one(self, host, spec):
                calls.append(("filter", "default", host))
                return True

        class LatencyFilter:
            def __init__(self, logger, config, monitoring):
                pass

            def before_filtering(self, hosts, spec):
                calls.append(("before", "latency"))

            def filter_one(self, host, spec):
                calls.append(("filter", "latency", host))
                return True

        self.filter_classes = {
            "DefaultFilter": DefaultFilter,
            "LatencyFilter": LatencyFilter,
        }
        self.write_config("""
[global]
default_profile=default
profile_hint_key=ext_sched_profile

[profile:default]
filters=DefaultFilter
weighers=

[profile:latency]
filters=LatencyFilter
weighers=
""")

        scheduler = self.make_scheduler()

        self.assertEqual(["host1"], scheduler.filter_all(["host1"], Spec()))
        self.assertIn(("filter", "default", "host1"), calls)

        calls.clear()
        spec = Spec({"ext_sched_profile": "latency"})
        self.assertEqual(["host2"], scheduler.filter_all(["host2"], spec))
        self.assertIn(("filter", "latency", "host2"), calls)
        self.assertNotIn(("filter", "default", "host2"), calls)

    def test_unknown_profile_rejects_all_hosts(self):
        class AllowFilter:
            def __init__(self, logger, config, monitoring):
                pass

            def before_filtering(self, hosts, spec):
                pass

            def filter_one(self, host, spec):
                return True

        self.filter_classes = {"AllowFilter": AllowFilter}
        self.write_config("""
[global]
default_profile=default
unknown_profile_policy=reject

[profile:default]
filters=AllowFilter
weighers=
""")

        scheduler = self.make_scheduler()
        spec = Spec({"ext_sched_profile": "missing"})
        self.assertEqual([], scheduler.filter_all(["host1"], spec))

    def test_legacy_enabled_filters_create_default_profile(self):
        calls = []

        class LegacyFilter:
            def __init__(self, logger, config, monitoring):
                pass

            def before_filtering(self, hosts, spec):
                calls.append("before")

            def filter_one(self, host, spec):
                calls.append(("filter", host))
                return True

        class LegacyWeight:
            def __init__(self, logger, config, monitoring):
                pass

            def before_weighting(self, hosts, spec):
                calls.append("before_weight")

            def weight_one(self, host, spec):
                return 3

        self.filter_classes = {"LegacyFilter": LegacyFilter}
        self.weigher_classes = {"LegacyWeight": LegacyWeight}
        self.write_config("""
[global]
enabled_filters=LegacyFilter
enabled_weighers=LegacyWeight
""")

        scheduler = self.make_scheduler()
        self.assertEqual(["host1"], scheduler.filter_all(["host1"], Spec()))
        self.assertEqual([3], scheduler.weigh_all([Weighed(Host())], Spec()))
        self.assertIn(("filter", "host1"), calls)
        self.assertIn("before_weight", calls)

    def test_weigh_all_sums_profile_weighers(self):
        class WeightOne:
            def __init__(self, logger, config, monitoring):
                pass

            def before_weighting(self, hosts, spec):
                pass

            def weight_one(self, host, spec):
                return 1

        class WeightMinusTwo:
            def __init__(self, logger, config, monitoring):
                pass

            def before_weighting(self, hosts, spec):
                pass

            def weight_one(self, host, spec):
                return -2

        self.weigher_classes = {
            "WeightOne": WeightOne,
            "WeightMinusTwo": WeightMinusTwo,
        }
        self.write_config("""
[global]
default_profile=default

[profile:default]
filters=
weighers=WeightOne,WeightMinusTwo
""")

        scheduler = self.make_scheduler()
        weights = scheduler.weigh_all(
            [Weighed(Host()), Weighed(Host())],
            Spec(),
        )
        self.assertEqual([-1, -1], weights)

    def test_invalid_hot_reload_keeps_previous_state(self):
        class AllowFilter:
            def __init__(self, logger, config, monitoring):
                pass

            def before_filtering(self, hosts, spec):
                pass

            def filter_one(self, host, spec):
                return True

        self.filter_classes = {"AllowFilter": AllowFilter}
        self.write_config("""
[global]
default_profile=default

[profile:default]
filters=AllowFilter
weighers=
""")

        scheduler = self.make_scheduler()
        self.assertEqual(["host1"], scheduler.filter_all(["host1"], Spec()))
        state = scheduler.state

        self.write_config("""
[global]
default_profile=default

[profile:default]
filters=MissingFilter
weighers=
""")

        self.assertEqual(["host2"], scheduler.filter_all(["host2"], Spec()))
        self.assertIs(state, scheduler.state)

    def test_parallel_requests_do_not_share_profile_state(self):
        slow_ready = threading.Event()
        release_slow = threading.Event()
        slow_result = []
        deny_result = []

        class SlowAllowFilter:
            def __init__(self, logger, config, monitoring):
                self.before_ran = False

            def before_filtering(self, hosts, spec):
                self.before_ran = True
                slow_ready.set()
                if not release_slow.wait(timeout=2):
                    raise AssertionError("timed out waiting for slow request")

            def filter_one(self, host, spec):
                return self.before_ran

        class DenyFilter:
            def __init__(self, logger, config, monitoring):
                pass

            def before_filtering(self, hosts, spec):
                pass

            def filter_one(self, host, spec):
                return False

        self.filter_classes = {
            "SlowAllowFilter": SlowAllowFilter,
            "DenyFilter": DenyFilter,
        }
        self.write_config("""
[global]
default_profile=slow

[profile:slow]
filters=SlowAllowFilter
weighers=

[profile:deny]
filters=DenyFilter
weighers=
""")

        scheduler = self.make_scheduler()

        def run_slow():
            slow_result.extend(scheduler.filter_all(["slow"], Spec()))

        thread = threading.Thread(target=run_slow)
        thread.start()
        self.assertTrue(slow_ready.wait(timeout=2))

        deny_spec = Spec({"ext_sched_profile": "deny"})
        deny_result.extend(scheduler.filter_all(["deny"], deny_spec))
        release_slow.set()
        thread.join(timeout=2)

        self.assertEqual([], deny_result)
        self.assertEqual(["slow"], slow_result)

    def test_request_started_before_reload_uses_old_snapshot(self):
        slow_ready = threading.Event()
        release_slow = threading.Event()
        slow_result = []

        class SlowAllowFilter:
            def __init__(self, logger, config, monitoring):
                self.before_ran = False

            def before_filtering(self, hosts, spec):
                self.before_ran = True
                slow_ready.set()
                if not release_slow.wait(timeout=2):
                    raise AssertionError("timed out waiting for slow request")

            def filter_one(self, host, spec):
                return self.before_ran

        class DenyFilter:
            def __init__(self, logger, config, monitoring):
                pass

            def before_filtering(self, hosts, spec):
                pass

            def filter_one(self, host, spec):
                return False

        self.filter_classes = {
            "SlowAllowFilter": SlowAllowFilter,
            "DenyFilter": DenyFilter,
        }
        self.write_config("""
[global]
default_profile=default

[profile:default]
filters=SlowAllowFilter
weighers=
""")

        scheduler = self.make_scheduler()

        def run_slow():
            slow_result.extend(scheduler.filter_all(["old"], Spec()))

        thread = threading.Thread(target=run_slow)
        thread.start()
        self.assertTrue(slow_ready.wait(timeout=2))

        self.write_config("""
[global]
default_profile=default

[profile:default]
filters=DenyFilter
weighers=
""")
        self.assertEqual([], scheduler.filter_all(["new"], Spec()))

        release_slow.set()
        thread.join(timeout=2)
        self.assertEqual(["old"], slow_result)


class TestPrometheusEndpoint(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock()
        self.mock_config = MagicMock()
        self.prom = plugin.PrometheusEndpoint(self.mock_logger, self.mock_config)

    @patch("external_scheduler.plugin.requests.get")
    def test_query_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "result": [
                    {"metric": {"instance": "host1"}, "value": [1234567890, "42.0"]},
                    {"metric": {"instance": "host2"}, "value": [1234567890, "84.5"]}
                ]
            }
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.prom.query("some_query")

        self.assertEqual(result, {"host1": 42.0, "host2": 84.5})
        mock_get.assert_called_once()
        self.mock_logger.error.assert_not_called()

    @patch("external_scheduler.plugin.requests.get", side_effect=requests.exceptions.Timeout)
    def test_query_timeout(self, mock_get):
        result = self.prom.query("some_query")
        self.assertEqual(result, {})
        self.mock_logger.error.assert_called_once()
        self.assertIn("time-out", self.mock_logger.error.call_args[0][0])

    @patch("external_scheduler.plugin.requests.get", side_effect=requests.exceptions.RequestException("fail"))
    def test_query_request_exception(self, mock_get):
        result = self.prom.query("some_query")
        self.assertEqual(result, {})
        self.mock_logger.error.assert_called_once()
        self.assertIn("error querying", self.mock_logger.error.call_args[0][0])

    @patch("external_scheduler.plugin.requests.get")
    def test_query_unexpected_exception(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("unexpected")
        mock_get.return_value = mock_response

        result = self.prom.query("some_query")
        self.assertEqual(result, {})
        self.mock_logger.error.assert_called_once()
        self.assertIn("error in plugin", self.mock_logger.error.call_args[0][0])

    def test_get_endpoint_single(self):
        self.prom.endpoint = "http://single-endpoint"
        self.assertEqual(self.prom.get_endpoint(), "http://single-endpoint")

    def test_get_endpoint_multiple(self):
        endpoints = ["http://a", "http://b", "http://c"]
        self.prom.endpoint = endpoints
        self.assertIn(self.prom.get_endpoint(), endpoints)


if __name__ == '__main__':
    unittest.main()
