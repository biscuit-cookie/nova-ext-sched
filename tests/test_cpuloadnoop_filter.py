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
from external_scheduler.filters import CpuLoadNoopFilter

class TestCpuLoadNoopFilter(unittest.TestCase):

    def setUp(self):
        self.mock_logger = MagicMock()
        self.mock_config = MagicMock()
        self.mock_config.getfloat.side_effect = lambda s, o, fallback=None: {
            ("cpu_load", "degree"): 1.65,
            ("cpu_load", "load"): 0.8,
            ("cpu_load", "exclude_alloc"): 0.8
        }.get((s,o), fallback)
        self.mock_monitoring = MagicMock()

        self.filter = CpuLoadNoopFilter(self.mock_logger, self.mock_config, self.mock_monitoring)

    @patch('time.time')
    def test_before_filtering_calls_super_and_logs(self, mock_time):
        # Simulate time flow
        mock_time.side_effect = [1000, 1000.2]  # 200 ms duration

        host1 = MagicMock()
        host1.nodename = "host1"
        host1.vcpus_used = 9
        host1.vcpus_total = 10

        host2 = MagicMock()
        host2.nodename = "host2"
        host2.vcpus_used = 6
        host2.vcpus_total = 10

        with patch('external_scheduler.filters.CpuLoadFilter.filter_one', side_effect=[True, False]) as mock_parent_filter_one:
            self.filter.before_filtering([host1, host2], spec_obj={})
            self.assertEqual(mock_parent_filter_one.call_count, 2)

        self.mock_logger.info.assert_called()
        log_msg = self.mock_logger.info.call_args[0][0]
        self.assertIn("filtered|total|duration", log_msg)
        self.assertIn("1|2|200", log_msg)  # filtered=1 (host2), total=2, duration approx 200

    def test_filter_one_always_returns_true(self):
        host = MagicMock()
        spec = MagicMock()
        with patch('external_scheduler.filters.CpuLoadFilter.filter_one', return_value=False):
            result = self.filter.filter_one(host, spec)

        self.assertTrue(result)

if __name__ == "__main__":
    unittest.main()
