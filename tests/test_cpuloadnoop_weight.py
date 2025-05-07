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
from unittest.mock import MagicMock, patch
import statistics
from external_scheduler.weights import CpuLoadNoopWeight

class TestCpuLoadNoopWeight(unittest.TestCase):

    def setUp(self):
        self.mock_logger = MagicMock()
        self.mock_config = MagicMock()
        self.mock_config.getfloat.side_effect = lambda s, o, fallback=None: {
            ("cpu_load", "degree"): 1.65,
            ("cpu_load", "load"): 0.8,
            ("cpu_load", "exclude_alloc"): 0.8
        }.get((s,o), fallback)
        self.mock_monitoring = MagicMock()

        self.filter = CpuLoadNoopWeight(self.mock_logger, self.mock_config, self.mock_monitoring)

    @patch('time.time')
    def test_before_weighting_calls_super_and_logs(self, mock_time):
        # Simulate time flow
        mock_time.side_effect = [1000, 1000.2]  # 200 ms duration

        host1 = MagicMock()
        host1.obj.host = "host1"
        host1.obj.vcpus_used = 9
        host1.obj.vcpus_total = 10

        host2 = MagicMock()
        host2.obj.host = "host2"
        host2.obj.vcpus_used = 6
        host2.obj.vcpus_total = 10

        with patch('external_scheduler.weights.CpuLoadWeight.weight_one', side_effect=[5, 10]) as mock_parent_weight_one:
            self.filter.before_weighting([host1, host2], weight_properties={})

            self.assertEqual(mock_parent_weight_one.call_count, 2)

        self.mock_logger.info.assert_called()
        log_msg = self.mock_logger.info.call_args[0][0]

        self.assertIn("min|max|avg|q50|duration", log_msg)
        self.assertIn("5|10", log_msg)  # min=5 max=10
        self.assertIn("7.5", log_msg)   # avg = (5+10)/2 = 7.5
        self.assertIn("7.5", log_msg)   # median = 7.5
        self.assertIn("200", log_msg)   # durée ~ 200 ms

    def test_weight_one_always_returns_zero(self):
        host_state = MagicMock()
        weight_properties = {}
        with patch('external_scheduler.weights.CpuLoadWeight.weight_one', return_value=10):
            result = self.filter.weight_one(host_state, weight_properties)
        self.assertEqual(result, 0)

if __name__ == "__main__":
    unittest.main()
