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
from external_scheduler.weights.base_weigher import BaseExternalWeigher

class TestBaseExternalWeigher(unittest.TestCase):
    def setUp(self):
        self.weigher = BaseExternalWeigher()

    def test_before_weighting_does_nothing(self):
        result = self.weigher.before_weighting(['dummy_host'], {'some': 'weights'})
        self.assertIsNone(result)

    def test_weight_one_returns_zero(self):
        result = self.weigher.weight_one('dummy_host', {'some': 'weights'})
        self.assertEqual(result, 0)
