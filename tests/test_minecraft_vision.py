import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

import app as jarvis
from integrations.minecraft import MinecraftGameState, minecraft_state_store
from integrations.minecraft_vision import MAX_SCREENSHOT_BYTES, screenshot_analysis_store

VISION_TOKEN = "test-vision-ticket-key"


def test_fixture_image(image_format="PNG", color=(30, 120, 40)):
    """Generate labeled synthetic pixels for tests only; this is not gameplay imagery."""
    image = Image.new("RGB", (40, 30), color)
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


class MinecraftVisionTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "MINECRAFT_API_TOKEN": VISION_TOKEN,
            "MINECRAFT_VISION_ENABLED": "false",
        })
        self.environment.start()
        self.client = TestClient(jarvis.app)
        self.sessions = [uuid4(), uuid4(), uuid4(), uuid4()]

    def tearDown(self):
        self.client.close()
        self.environment.stop()

    def enable_vision(self):
        os.environ["MINECRAFT_VISION_ENABLED"] = "true"

    def ticket(self, session_id):
        response = self.client.post(
            "/api/minecraft/vision-ticket",
            headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
            json={"session_id": str(session_id)},
        )
        return response

    def upload(self, session_id, ticket, image_bytes=None, filename="test-fixture.png", captured_at=None, basis="live-capture"):
        image_bytes = image_bytes if image_bytes is not None else test_fixture_image()
        data = {"timestamp_basis": basis}
        if captured_at is not None:
            data["captured_at"] = captured_at
        return self.client.post(
            "/api/minecraft/screenshot",
            headers={"X-Jarvis-Vision-Ticket": ticket},
            data=data,
            files={"file": (filename, image_bytes, "image/png")},
        )

    def test_vision_is_disabled_until_server_opt_in(self):
        response = self.ticket(self.sessions[0])
        self.assertEqual(response.status_code, 404)
        self.assertEqual(jarvis.health()["minecraft_vision_enabled"], False)

    def test_ticket_requires_same_origin_and_upload_requires_valid_ticket(self):
        self.enable_vision()
        denied = self.client.post(
            "/api/minecraft/vision-ticket",
            headers={"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
            json={"session_id": str(self.sessions[0])},
        )
        self.assertEqual(denied.status_code, 403)
        unauthenticated = self.upload(self.sessions[0], "invalid")
        self.assertEqual(unauthenticated.status_code, 401)

    def test_accepts_png_and_jpeg_and_sends_gemini_image_part(self):
        self.enable_vision()
        fake_client = Mock()
        fake_client.models.generate_content.return_value = SimpleNamespace(text="TEST FIXTURE: A green region is visible; no entities can be confirmed.")
        with patch("integrations.minecraft_vision._client_provider", return_value=fake_client):
            for session_id, image_format, extension in (
                (self.sessions[0], "PNG", "png"),
                (self.sessions[1], "JPEG", "jpg"),
            ):
                ticket = self.ticket(session_id).json()["ticket"]
                response = self.upload(
                    session_id,
                    ticket,
                    test_fixture_image(image_format),
                    filename=f"test-fixture.{extension}",
                    captured_at=datetime.now(timezone.utc).isoformat(),
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "fresh")
                self.assertIn("TEST FIXTURE", response.json()["analysis"])
                self.assertEqual(response.json()["test_mode"], False)

        self.assertEqual(fake_client.models.generate_content.call_count, 2)
        parts = fake_client.models.generate_content.call_args.kwargs["contents"]
        self.assertEqual(parts[0].inline_data.mime_type, "image/jpeg")
        self.assertIn("Screenshot capture timestamp", parts[1])

    def test_invalid_images_oversize_and_invalid_timestamps_are_rejected(self):
        self.enable_vision()
        ticket = self.ticket(self.sessions[0]).json()["ticket"]
        invalid = self.upload(self.sessions[0], ticket, b"not an image")
        self.assertEqual(invalid.status_code, 422)
        oversized = self.upload(self.sessions[0], ticket, b"x" * (MAX_SCREENSHOT_BYTES + 1))
        self.assertEqual(oversized.status_code, 413)
        future = self.upload(
            self.sessions[1],
            self.ticket(self.sessions[1]).json()["ticket"],
            captured_at=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
        )
        self.assertEqual(future.status_code, 422)

    def test_unknown_and_old_file_timestamps_are_marked_stale(self):
        self.enable_vision()
        fake_client = Mock()
        fake_client.models.generate_content.return_value = SimpleNamespace(text="Test fixture analysis.")
        with patch("integrations.minecraft_vision._client_provider", return_value=fake_client):
            ticket = self.ticket(self.sessions[0]).json()["ticket"]
            unknown = self.upload(self.sessions[0], ticket, basis="unknown")
            self.assertEqual(unknown.status_code, 200)
            self.assertEqual(unknown.json()["status"], "stale")
            self.assertIsNone(unknown.json()["captured_at"])

            old_session = self.sessions[1]
            old_ticket = self.ticket(old_session).json()["ticket"]
            old_time = datetime.now(timezone.utc) - timedelta(minutes=5)
            old = self.upload(old_session, old_ticket, captured_at=old_time.isoformat(), basis="file-modified")
            self.assertEqual(old.status_code, 200)
            self.assertEqual(old.json()["status"], "stale")

    def test_duplicate_screenshot_is_cached_without_a_second_gemini_call(self):
        self.enable_vision()
        fake_client = Mock()
        fake_client.models.generate_content.return_value = SimpleNamespace(text="Fixture deduplicated.")
        with patch("integrations.minecraft_vision._client_provider", return_value=fake_client):
            session_id = self.sessions[0]
            ticket = self.ticket(session_id).json()["ticket"]
            image = test_fixture_image()
            first = self.upload(session_id, ticket, image)
            second = self.upload(session_id, ticket, image)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["cached"])
        self.assertEqual(fake_client.models.generate_content.call_count, 1)

    def test_latest_vision_and_fabric_state_are_combined_on_next_chat_turn(self):
        self.enable_vision()
        session_id = self.sessions[0]
        state = MinecraftGameState.model_validate({
            "player_username": "Alex", "x": 12.0, "y": 70.0, "z": -4.0,
            "health": 18.0, "hunger": 16, "armor_points": 4,
            "held_item": None, "inventory": [], "biome": "minecraft:forest",
            "dimension": "minecraft:overworld", "game_mode": "survival", "xp_level": 3,
            "time_of_day": 2000, "alive": True,
        })
        minecraft_state_store.update(session_id, state)
        vision_client = Mock()
        vision_client.models.generate_content.return_value = SimpleNamespace(
            text="TEST FIXTURE: A chest is visible near a river; image detail is uncertain."
        )
        timestamp = datetime.now(timezone.utc).isoformat()
        with patch("integrations.minecraft_vision._client_provider", return_value=vision_client):
            ticket = self.ticket(session_id).json()["ticket"]
            response = self.upload(
                session_id,
                ticket,
                captured_at=timestamp,
                basis="live-capture",
            )
        self.assertEqual(response.status_code, 200)
        vision_calls = vision_client.models.generate_content.call_count
        chat_client = Mock()
        chat_client.models.generate_content.return_value = SimpleNamespace(text="I can see a chest, and your player state shows forest coordinates.")
        with patch.object(jarvis, "_client", chat_client), patch.object(jarvis, "MODEL_NAME", "gemini-3.8-flash"):
            jarvis.chat(jarvis.ChatRequest(session_id=str(session_id), message="What is around me?"))

        prompt = chat_client.models.generate_content.call_args.kwargs["config"].system_instruction
        self.assertIn('"x":12.0', prompt)
        self.assertIn("A chest is visible near a river", prompt)
        self.assertIn("timestamp_basis", prompt)
        self.assertEqual(vision_client.models.generate_content.call_count, vision_calls)

    def test_vision_failure_is_sanitized_and_does_not_log_image_bytes(self):
        self.enable_vision()
        fake_client = Mock()
        fake_client.models.generate_content.side_effect = RuntimeError("provider failure with private image data")
        with patch("integrations.minecraft_vision._client_provider", return_value=fake_client):
            ticket = self.ticket(self.sessions[0]).json()["ticket"]
            response = self.upload(self.sessions[0], ticket)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("private image data", response.text)


if __name__ == "__main__":
    unittest.main()
