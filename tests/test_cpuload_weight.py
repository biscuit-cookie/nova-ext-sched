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

import unittest
from unittest.mock import MagicMock
from external_scheduler.weights import CpuLoadWeight

class TestCpuLoadWeight(unittest.TestCase):

    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_config.getfloat.side_effect = lambda section, option, fallback=None: {
            ("cpu_load", "degree"): 1.65,
            ("cpu_load", "load"): 0.85,
            ("cpu_load", "exclude_alloc"): 0.8
        }.get((section, option), fallback)

        self.mock_logger = MagicMock()
        self.mock_monitoring = MagicMock()

        self.filter = CpuLoadWeight(self.mock_logger, self.mock_config, self.mock_monitoring)

    def test_before_weighting_sets_idle_ratio_for_oversubscribed(self):
        self.mock_monitoring.query.return_value = {"hostA": 0.5}

        hostA_obj = MagicMock(host="hostA", vcpus_used=9, vcpus_total=10)
        hostB_obj = MagicMock(host="hostB", vcpus_used=5, vcpus_total=10)
        hostA = MagicMock(obj=hostA_obj)
        hostB = MagicMock(obj=hostB_obj)

        self.filter.before_weighting([hostA, hostB], weight_properties={})

        assert hostA_obj.__dict__['ext-sched.idle-ratio'] == 0.5
        assert 'ext-sched.idle-ratio' not in hostA.__dict__
        assert 'ext-sched.idle-ratio' not in hostB_obj.__dict__

    def test_weight_one_returns_0_if_no_idle_ratio(self):
        class AttrMock(MagicMock): # Ugly but otherwise, hasattr value always return True with mock objects
            def __getattr__(self, name):
                raise AttributeError(f"{name} not found")
        host = AttrMock(host="hostC", vcpus_total=10)
        self.assertEqual(self.filter.weight_one(host, {}), 0)

    def test_weight_one_computes_score(self):
        host = MagicMock(vcpus_total=10)
        setattr(host, 'ext-sched.idle-ratio', 0.7)

        expected_free = int((self.filter.load_target - (1 - 0.7)) * 10)
        self.assertEqual(self.filter.weight_one(host, {}), expected_free * self.filter.multiplier)

    def test_get_hosts_metric_builds_query_and_calls_monitoring(self):
        regex_host = "hostA|hostB"
        sigma = 1.65

        self.filter.get_hosts_metric(regex_host)

        expected_query = (
            f'rec_host_cpu_idle_q01{{instance=~"{regex_host}"}} - {sigma} * '
            f'rec_host_cpu_idle_std{{instance=~"{regex_host}"}}'
        )
        self.mock_monitoring.query.assert_called_once_with(expected_query)

if __name__ == "__main__":
    unittest.main()
