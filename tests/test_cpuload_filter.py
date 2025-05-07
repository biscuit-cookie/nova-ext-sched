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
from external_scheduler.filters.cpuload_filter import CpuLoadFilter

class TestCpuLoadFilter(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.config = MagicMock()
        self.monitoring = MagicMock()
        self.config.getfloat.side_effect = [1.25, 0.8, 0.8]  # sigma, load_target, exclude_alloc
        self.filter = CpuLoadFilter(self.logger, self.config, self.monitoring)

    def test_init_sets_parameters(self):
        self.assertEqual(self.filter.sigma, 1.25)
        self.assertEqual(self.filter.load_target, 0.8)
        self.assertEqual(self.filter.exclude_alloc, 0.8)
        self.assertEqual(self.filter.monitoring, self.monitoring)

    def test_before_filtering_sets_idle_ratio_only_for_oversubscribed(self):
        self.filter.get_hosts_metric = MagicMock(return_value={"host1": 0.6})

        h1 = MagicMock(nodename="host1", vcpus_total=10, vcpus_used=9)
        h2 = MagicMock(nodename="host2", vcpus_total=10, vcpus_used=6)
        self.filter.before_filtering([h1, h2], spec_obj={})

        assert h1.__getattribute__('ext-sched.idle-ratio') == 0.6
        assert 'ext-sched.idle-ratio' not in h2.__dict__

    def test_filter_one_returns_true_when_enough_capacity(self):
        self.filter.load_target = 0.9
        host = MagicMock(nodename="hostA", vcpus_total=10)
        setattr(host, 'ext-sched.idle-ratio', 0.7)
        spec = MagicMock(vcpus=2)
        self.assertTrue(self.filter.filter_one(host, spec))

    def test_filter_one_returns_false_when_not_enough_capacity(self):
        self.filter.load_target = 0.7
        host = MagicMock(nodename="hostB", vcpus_total=10)
        setattr(host, 'ext-sched.idle-ratio', 0.4)
        spec = MagicMock(vcpus=5)
        self.assertFalse(self.filter.filter_one(host, spec))

    def test_filter_one_with_no_idle_ratio_assumes_idle(self):
        self.filter.load_target = 0.9
        class AttrMock(MagicMock): # Ugly but otherwise, hasattr value always return True with mock objects
            def __getattr__(self, name):
                raise AttributeError(f"{name} not found")
        host = AttrMock(nodename="hostC", vcpus_total=10)
        spec = MagicMock(vcpus=5)
        self.assertTrue(self.filter.filter_one(host, spec))

    def test_get_hosts_metric_queries_with_correct_expression(self):
        self.filter.get_hosts_metric("h1|h2")
        expected = 'rec_host_cpu_idle_q01{instance=~"h1|h2"} - 1.25 * rec_host_cpu_idle_std{instance=~"h1|h2"}'
        self.monitoring.query.assert_called_once_with(expected)
