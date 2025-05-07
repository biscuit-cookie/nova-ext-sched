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

import unittest, requests
from unittest.mock import MagicMock, patch
from external_scheduler import plugin

class TestExternalScheduler(unittest.TestCase):

    def setUp(self):
        self.plugin = plugin.ExternalScheduler(logger=MagicMock())
        # Mock objects
        self.mock_filter_true = MagicMock()
        self.mock_filter_true.filter_one.return_value = True
        self.mock_filter_false = MagicMock()
        self.mock_filter_false.filter_one.return_value = False
        self.mock_weigher_one = MagicMock()
        self.mock_weigher_one.weight_one.return_value = 1
        self.mock_weigher_minus_two = MagicMock()
        self.mock_weigher_minus_two.weight_one.return_value = -2

    # Filters test

    def test_before_filtering_calls_filters(self):
        host_list = ['host1', 'host2']
        spec_obj = {'some': 'spec'}

        self.mock_filter_true.reset_mock()
        self.mock_filter_false.reset_mock()

        self.plugin.filter_list = []
        self.assertIsNone(self.plugin.before_filtering(host_list, spec_obj))
        
        self.plugin.filter_list = [self.mock_filter_true, self.mock_filter_false]
        self.assertIsNone(self.plugin.before_filtering(host_list, spec_obj))
        self.mock_filter_true.before_filtering.assert_called_once_with(host_list, spec_obj)
        self.mock_filter_false.before_filtering.assert_called_once_with(host_list, spec_obj)

    def test_filter_one_with_no_filters_returns_true(self):
        self.plugin.filter_list = []
        result = self.plugin.filter_one('host', 'spec')
        self.assertTrue(result)

    def test_filter_one_with_single_filter(self):
        self.mock_filter_true.reset_mock()
        self.mock_filter_false.reset_mock()
        
        self.plugin.filter_list = [self.mock_filter_true]
        self.assertTrue(self.plugin.filter_one('host', 'spec'))
        self.mock_filter_true.filter_one.assert_called_once_with('host', 'spec')
        
        self.plugin.filter_list = [self.mock_filter_false]
        self.assertFalse(self.plugin.filter_one('host', 'spec'))
        self.mock_filter_false.filter_one.assert_called_once_with('host', 'spec')
        
    def test_filter_one_with_multiple_filters(self):
        self.mock_filter_true.reset_mock()
        self.plugin.filter_list = [self.mock_filter_true, self.mock_filter_true]
        self.assertTrue(self.plugin.filter_one('host', 'spec'))
        self.assertEqual(self.mock_filter_true.filter_one.call_count, 2)
        
        self.mock_filter_false.reset_mock()
        self.plugin.filter_list = [self.mock_filter_false, self.mock_filter_false]
        self.assertFalse(self.plugin.filter_one('host', 'spec'))
        self.assertEqual(self.mock_filter_false.filter_one.call_count, 1)

        self.mock_filter_true.reset_mock()
        self.mock_filter_false.reset_mock()
        self.plugin.filter_list = [self.mock_filter_true, self.mock_filter_false]
        self.assertFalse(self.plugin.filter_one('host', 'spec'))
        self.mock_filter_true.filter_one.assert_called_once_with('host', 'spec')
        self.mock_filter_false.filter_one.assert_called_once_with('host', 'spec')

     # Weigher test

    def test_before_weighting_calls_weighers(self):
        host_list = ['host1', 'host2']
        weight_props = {'some': 'spec'}

        self.mock_weigher_one.reset_mock()
        self.mock_weigher_minus_two.reset_mock()

        self.plugin.weight_list = []
        self.assertIsNone(self.plugin.before_weighting(host_list, weight_props))
        
        self.plugin.weight_list = [self.mock_weigher_one,self.mock_weigher_minus_two]
        self.assertIsNone(self.plugin.before_weighting(host_list, weight_props))
        self.mock_weigher_one.before_weighting.assert_called_once_with(host_list, weight_props)
        self.mock_weigher_minus_two.before_weighting.assert_called_once_with(host_list, weight_props)

    def test_weight_one_with_no_weighers_returns_zero(self):
        self.plugin.weight_list = []
        score = self.plugin.weight_one('host', 'props')
        self.assertEqual(score, 0)

    def test_weight_one_accumulates_scores(self):
        self.mock_weigher_one.reset_mock()
        self.mock_weigher_minus_two.reset_mock()

        self.plugin.weight_list = [self.mock_weigher_one]
        self.assertEqual(self.plugin.weight_one('host', 'props'), self.mock_weigher_one.weight_one.return_value)

        self.plugin.weight_list = [self.mock_weigher_one,self.mock_weigher_minus_two]
        self.assertEqual(self.plugin.weight_one('host', 'props'), self.mock_weigher_one.weight_one.return_value + self.mock_weigher_minus_two.weight_one.return_value)

        self.plugin.weight_list = [self.mock_weigher_minus_two, self.mock_weigher_one]
        self.assertEqual(self.plugin.weight_one('host', 'props'), self.mock_weigher_one.weight_one.return_value + self.mock_weigher_minus_two.weight_one.return_value)

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