import json
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import Booking, BookingStatus
from app.services.ota_agent.extractor import OTAExtractor
from app.services.ota_agent.integration import OTAAgent


class OTAAIExtractorRetryTests(unittest.TestCase):
    def setUp(self):
        self.extractor = OTAExtractor()
        self.extractor.api_key = "test-key"
        self.extractor.client = True
        self.extractor.fallback_models = []
        self.request = httpx.Request("POST", "https://gatecheap.io.vn/v1/chat/completions")

    def _response(self, payload, status_code=200):
        return httpx.Response(status_code, json=payload, request=self.request)

    @patch("app.services.ota_agent.extractor.time.sleep")
    @patch("app.services.ota_agent.extractor._wait_for_api_slot")
    @patch("app.services.ota_agent.extractor.httpx.post")
    def test_retries_empty_content_five_times_with_30_second_delays(self, mock_post, _mock_wait, mock_sleep):
        mock_post.side_effect = [
            self._response({"choices": [{"message": {"content": ""}}]})
            for _ in range(5)
        ]

        data = self.extractor.extract_data("<p>booking</p>", "info.mail@go2joy.vn", "Go2Joy booking")

        self.assertEqual(data["status"], "FAILED")
        self.assertEqual(mock_post.call_count, 5)
        self.assertEqual(mock_sleep.call_count, 4)
        mock_sleep.assert_called_with(30)

    @patch("app.services.ota_agent.extractor.time.sleep")
    @patch("app.services.ota_agent.extractor._wait_for_api_slot")
    @patch("app.services.ota_agent.extractor.httpx.post")
    def test_succeeds_when_fifth_attempt_returns_valid_json(self, mock_post, _mock_wait, mock_sleep):
        valid_payload = {
            "action_type": "NEW",
            "booking_source": "Go2Joy",
            "external_id": "4505305",
        }
        mock_post.side_effect = [
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": json.dumps(valid_payload)}}]}),
        ]

        data = self.extractor.extract_data("<p>booking</p>", "info.mail@go2joy.vn", "Go2Joy booking")

        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["external_id"], "4505305")
        self.assertEqual(mock_post.call_count, 5)
        self.assertEqual(mock_sleep.call_count, 4)

    @patch("app.services.ota_agent.extractor.time.sleep")
    @patch("app.services.ota_agent.extractor._wait_for_api_slot")
    @patch("app.services.ota_agent.extractor.httpx.post")
    def test_retries_transient_http_errors_five_times(self, mock_post, _mock_wait, mock_sleep):
        mock_post.side_effect = [
            self._response({"error": "bad gateway"}, status_code=502)
            for _ in range(5)
        ]

        data = self.extractor.extract_data("<p>booking</p>", "noreply@traveloka.com", "Traveloka booking")

        self.assertEqual(data["status"], "FAILED")
        self.assertEqual(mock_post.call_count, 5)
        self.assertEqual(mock_sleep.call_count, 4)
        mock_sleep.assert_called_with(30)

    @patch("app.services.ota_agent.extractor.time.sleep")
    @patch("app.services.ota_agent.extractor._wait_for_api_slot")
    @patch("app.services.ota_agent.extractor.httpx.post")
    def test_uses_fallback_model_after_primary_model_retries_fail(self, mock_post, _mock_wait, mock_sleep):
        self.extractor.model = "gpt-5.5"
        self.extractor.fallback_models = ["deepseek-v4-pro"]
        valid_payload = {
            "action_type": "NEW",
            "booking_source": "Go2Joy",
            "external_id": "4505305",
        }
        mock_post.side_effect = [
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": "Menu"}}]}),
            self._response({"choices": [{"message": {"content": json.dumps(valid_payload)}}]}),
        ]

        data = self.extractor.extract_data("<p>booking</p>", "info.mail@go2joy.vn", "Go2Joy booking")

        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["external_id"], "4505305")
        called_models = [call.kwargs["json"]["model"] for call in mock_post.call_args_list]
        self.assertEqual(called_models[:5], ["gpt-5.5"] * 5)
        self.assertEqual(called_models[5], "deepseek-v4-pro")
        self.assertEqual(mock_sleep.call_count, 4)

    @patch("app.services.ota_agent.extractor.time.sleep")
    @patch("app.services.ota_agent.extractor._wait_for_api_slot")
    @patch("app.services.ota_agent.extractor.httpx.post")
    def test_tries_second_fallback_after_first_fallback_fails(self, mock_post, _mock_wait, _mock_sleep):
        self.extractor.model = "gpt-5.5"
        self.extractor.fallback_models = ["deepseek-v4-pro", "gpt-5.4"]
        valid_payload = {
            "action_type": "NEW",
            "booking_source": "Go2Joy",
            "external_id": "4505305",
        }
        mock_post.side_effect = [
            *[self._response({"choices": [{"message": {"content": "Menu"}}]}) for _ in range(10)],
            self._response({"choices": [{"message": {"content": json.dumps(valid_payload)}}]}),
        ]

        data = self.extractor.extract_data("<p>booking</p>", "info.mail@go2joy.vn", "Go2Joy booking")

        self.assertEqual(data["status"], "SUCCESS")
        called_models = [call.kwargs["json"]["model"] for call in mock_post.call_args_list]
        self.assertEqual(called_models[:5], ["gpt-5.5"] * 5)
        self.assertEqual(called_models[5:10], ["deepseek-v4-pro"] * 5)
        self.assertEqual(called_models[10], "gpt-5.4")


class OTAAIAgentValidationTests(unittest.TestCase):
    def setUp(self):
        self.agent = OTAAgent()

    def test_normalizes_ai_action_aliases_before_upsert(self):
        data = self.agent._normalize_extracted_data({
            "action_type": "CANCELLED",
            "booking_source": "Go2Joy",
            "external_id": "4505305",
            "deposit_amount": 100000,
        })

        self.assertEqual(data["action_type"], "CANCEL")
        self.assertEqual(data["deposit_amount"], 0)

    def test_validates_cancel_without_dates_or_room_type(self):
        data = self.agent._normalize_extracted_data({
            "action_type": "CANCELED",
            "booking_source": "Go2Joy",
            "external_id": "4505305",
        })

        self.agent._validate_extracted_booking(data)

    def test_rejects_new_booking_missing_required_ai_fields(self):
        data = self.agent._normalize_extracted_data({
            "action_type": "NEW",
            "booking_source": "Go2Joy",
            "external_id": "4505305",
            "check_in": "2026-05-15",
        })

        with self.assertRaises(ValueError):
            self.agent._validate_extracted_booking(data)

    def test_rejects_negative_ai_total_price(self):
        data = self.agent._normalize_extracted_data({
            "action_type": "NEW",
            "booking_source": "Go2Joy",
            "external_id": "4505305",
            "check_in": "2026-05-15",
            "check_out": "2026-05-16",
            "room_type": "Superior",
            "total_price": -1,
        })

        with self.assertRaises(ValueError):
            self.agent._validate_extracted_booking(data)

    def test_process_email_uses_ai_output_not_rule_output(self):
        booking = Booking(
            id=9,
            external_id="AI-4505305",
            booking_source="Go2Joy",
            guest_name="AI Guest",
            check_in=date(2026, 5, 15),
            check_out=date(2026, 5, 16),
            status=BookingStatus.CONFIRMED,
            reservation_status="PENDING",
            booking_type="OTA",
        )
        self.agent.extractor.extract_data = MagicMock(return_value={
            "status": "SUCCESS",
            "action_type": "NEW",
            "booking_source": "Go2Joy",
            "external_id": "AI-4505305",
            "guest_name": "AI Guest",
            "hotel_name": "Bin Bin Hotel 1",
            "check_in": "2026-05-15",
            "check_out": "2026-05-16",
            "room_type": "Superior",
            "num_rooms": 1,
            "total_price": 500000,
            "deposit_amount": 200000,
        })
        self.agent.rule_extractor.extract = MagicMock(return_value={
            "status": "SUCCESS",
            "action_type": "NEW",
            "booking_source": "Go2Joy",
            "external_id": "RULE-4505305",
        })
        self.agent.upsert_booking = MagicMock(return_value=booking)

        log = _Log()
        db = _Db(log)
        mapper = _Mapper()
        email = {
            "subject": "Go2Joy - Đặt phòng mới - 4505305",
            "sender": "info.mail@go2joy.vn",
            "html": "<p>booking</p>",
            "text": "booking",
            "message_id": "msg-ai-1",
        }

        self.agent.process_email(db, mapper, email)

        self.agent.extractor.extract_data.assert_called_once()
        self.agent.rule_extractor.extract.assert_not_called()
        upsert_data = self.agent.upsert_booking.call_args.args[1]
        self.assertEqual(upsert_data["external_id"], "AI-4505305")
        self.assertEqual(upsert_data["deposit_amount"], 0)
        self.assertEqual(db.log.status.value, "SUCCESS")

    def test_process_email_rejects_invalid_ai_success_before_upsert(self):
        self.agent.extractor.extract_data = MagicMock(return_value={
            "status": "SUCCESS",
            "action_type": "NEW",
            "booking_source": "Go2Joy",
            "external_id": "4505305",
        })
        self.agent.upsert_booking = MagicMock()

        log = _Log()
        db = _Db(log)
        mapper = _Mapper()
        email = {
            "subject": "Go2Joy - Đặt phòng mới - 4505305",
            "sender": "info.mail@go2joy.vn",
            "html": "<p>booking</p>",
            "text": "booking",
            "message_id": "msg-ai-2",
        }

        self.agent.process_email(db, mapper, email)

        self.agent.upsert_booking.assert_not_called()
        self.assertEqual(db.log.status.value, "FAILED")


class _Query:
    def __init__(self, item=None):
        self.item = item

    def filter(self, *conditions):
        return self

    def first(self):
        return None


class _Db:
    def __init__(self, log):
        self.log = log

    def query(self, model):
        return _Query()

    def add(self, obj):
        self.log = obj

    def commit(self):
        pass

    def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 1

    def rollback(self):
        pass


class _Log:
    id = 1
    status = None
    error_message = None
    error_traceback = None
    extracted_data = None
    booking_id = None
    retry_count = 0


class _Mapper:
    def get_branch_id_from_room_type(self, room_type):
        return None

    def get_branch_id(self, hotel_name):
        return 1


if __name__ == "__main__":
    unittest.main()
