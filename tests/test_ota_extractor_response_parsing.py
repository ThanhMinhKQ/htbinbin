import json
import unittest
from unittest.mock import patch

import httpx

from app.services.ota_agent.extractor import OTAExtractor


class OTAExtractorResponseParsingTests(unittest.TestCase):
    def setUp(self):
        self.extractor = OTAExtractor()
        self.extractor.api_key = "test-key"
        self.extractor.client = True
        self.request = httpx.Request("POST", "https://gatecheap.io.vn/v1/chat/completions")

    def _response(self, payload):
        return httpx.Response(200, json=payload, request=self.request)

    @patch("app.services.ota_agent.extractor.time.sleep")
    @patch("app.services.ota_agent.extractor._wait_for_api_slot")
    @patch("app.services.ota_agent.extractor.httpx.post")
    def test_retries_empty_ai_content_before_success(self, mock_post, _mock_wait, _mock_sleep):
        valid_payload = {
            "action_type": "NEW",
            "booking_source": "Traveloka",
            "external_id": "20261118583552",
            "hotel_name": "Bin Bin Hotel 6 - Near SECC D7",
        }
        mock_post.side_effect = [
            self._response({"choices": [{"message": {"content": ""}}]}),
            self._response({"choices": [{"message": {"content": json.dumps(valid_payload)}}]}),
        ]

        data = self.extractor.extract_data("<p>booking</p>", "noreply@traveloka.com", "Traveloka booking")

        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["external_id"], "20261118583552")
        self.assertEqual(mock_post.call_count, 2)

    @patch("app.services.ota_agent.extractor.time.sleep")
    @patch("app.services.ota_agent.extractor._wait_for_api_slot")
    @patch("app.services.ota_agent.extractor.httpx.post")
    def test_retries_invalid_json_content_until_success(self, mock_post, _mock_wait, _mock_sleep):
        valid_payload = {
            "action_type": "NEW",
            "booking_source": "Go2Joy",
            "external_id": "4501332",
        }
        mock_post.side_effect = [
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": "```json\n" + json.dumps(valid_payload) + "\n```"}}]}),
        ]

        data = self.extractor.extract_data("<p>booking</p>", "info.mail@go2joy.vn", "Go2Joy booking")

        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["external_id"], "4501332")
        self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
