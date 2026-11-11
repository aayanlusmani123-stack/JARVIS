import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException

import app as jarvis


class AppRuntimeTests(unittest.TestCase):
    def setUp(self):
        with jarvis._sessions_lock:
            jarvis._sessions.clear()

    def test_missing_api_key_returns_configuration_error(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}), patch.object(jarvis, "_client", None):
            with self.assertRaises(HTTPException) as raised:
                jarvis._get_client()

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("GEMINI_API_KEY", raised.exception.detail)

    def test_provider_failure_returns_sanitized_connection_error(self):
        client = Mock()
        client.models.generate_content.side_effect = RuntimeError("provider response with secret details")
        request = jarvis.ChatRequest(session_id=str(uuid4()), message="Hello")

        with patch.object(jarvis, "_get_client", return_value=client):
            with self.assertRaises(HTTPException) as raised:
                jarvis.chat(request)

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("connection and API key", raised.exception.detail)
        self.assertNotIn("secret details", raised.exception.detail)

    def test_chat_uses_bounded_recent_history_and_logs_timings(self):
        client = Mock()
        responses = iter(SimpleNamespace(text=f"Answer {index}") for index in range(10))
        client.models.generate_content.side_effect = lambda **kwargs: next(responses)
        session_id = str(uuid4())

        self.assertEqual(jarvis.DEFAULT_MODEL_NAME, "gemini-3.8-flash")
        with (
            patch.object(jarvis, "MODEL_NAME", "gemini-3.8-flash"),
            patch.object(jarvis, "_client", client),
            self.assertLogs("jarvis", level="INFO") as logs,
        ):
            for index in range(10):
                message = f"Question {index}: {'x' * 1800}"
                result = jarvis.chat(jarvis.ChatRequest(session_id=session_id, message=message))
                self.assertEqual(result["response"], f"Answer {index}")

        self.assertEqual(client.models.generate_content.call_count, 10)
        last_request = client.models.generate_content.call_args.kwargs
        self.assertEqual(last_request["model"], "gemini-3.8-flash")
        history_text = " ".join(part.text for content in last_request["contents"] for part in content.parts)
        self.assertNotIn("Question 0", history_text)
        self.assertIn("Question 9", history_text)
        self.assertLessEqual(len(history_text), jarvis.MAX_HISTORY_CHARS)
        self.assertRegex("\n".join(logs.output), r"api_ms=\d+\.\d+ total_ms=\d+\.\d+")

    def test_health_does_not_expose_api_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            result = jarvis.health()

        self.assertTrue(result["gemini_configured"])
        self.assertNotIn("test-secret", str(result))


if __name__ == "__main__":
    unittest.main()
