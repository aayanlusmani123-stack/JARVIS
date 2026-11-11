import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

import app as jarvis
from integrations.minecraft import (
    MINECRAFT_STATE_STALE_AFTER_SECONDS,
    MinecraftGameState,
    MinecraftStateStore,
    minecraft_state_store,
)


API_TOKEN = "test-minecraft-token"
AUTH_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


def game_state(**overrides):
    state = {
        "player_username": "Alex",
        "x": 1.5,
        "y": 64.0,
        "z": -12.25,
        "health": 18.0,
        "hunger": 16,
        "armor_points": 12,
        "held_item": {"item_id": "minecraft:iron_sword", "count": 1, "slot": 0},
        "inventory": [{"item_id": "minecraft:bread", "count": 3, "slot": 1}],
        "biome": "minecraft:plains",
        "dimension": "minecraft:overworld",
        "game_mode": "survival",
        "xp_level": 7,
        "time_of_day": 1000,
        "alive": True,
    }
    state.update(overrides)
    return state


class MinecraftApiTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"MINECRAFT_API_TOKEN": API_TOKEN})
        self.environment.start()
        self.client = TestClient(jarvis.app)
        self.sessions = [uuid4(), uuid4(), uuid4()]
        for session_id in self.sessions:
            minecraft_state_store.clear(session_id)
            with jarvis._sessions_lock:
                jarvis._sessions.pop(str(session_id), None)

    def tearDown(self):
        self.client.close()
        for session_id in self.sessions:
            minecraft_state_store.clear(session_id)
        self.environment.stop()

    def update(self, session_id, state=None, headers=None):
        return self.client.post(
            "/api/minecraft/update",
            headers=AUTH_HEADERS if headers is None else headers,
            json={"session_id": str(session_id), "state": state or game_state()},
        )

    def issue_event_ticket(self, session_id, headers=None):
        return self.client.post(
            "/api/minecraft/events-ticket",
            headers=headers or {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
            json={"session_id": str(session_id)},
        )

    def test_valid_state_is_validated_stored_and_returned(self):
        session_id = self.sessions[0]
        update = self.update(session_id)
        self.assertEqual(update.status_code, 200)
        self.assertTrue(update.json()["accepted"])

        result = self.client.get(
            "/api/minecraft/state",
            params={"session_id": str(session_id)},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(result.status_code, 200)
        body = result.json()
        self.assertEqual(body["status"], "fresh")
        self.assertEqual(body["state"]["player_username"], "Alex")
        self.assertEqual(body["state"]["inventory"][0]["item_id"], "minecraft:bread")
        self.assertIsNotNone(body["updated_at"])

    def test_invalid_values_and_extra_fields_are_rejected(self):
        self.assertEqual(self.update(self.sessions[0], game_state(health=1025)).status_code, 422)
        self.assertEqual(self.update(self.sessions[0], game_state(hunger=-1)).status_code, 422)
        self.assertEqual(self.update(self.sessions[0], game_state(player_username="bad name")).status_code, 422)
        self.assertEqual(self.update(self.sessions[0], game_state(unexpected=True)).status_code, 422)

    def test_bearer_token_is_required_for_state_access(self):
        response = self.update(self.sessions[0], headers={})
        self.assertEqual(response.status_code, 401)
        response = self.client.get(
            "/api/minecraft/state",
            params={"session_id": str(self.sessions[0])},
            headers={"Authorization": "Bearer wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_api_is_disabled_when_server_token_is_not_configured(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MINECRAFT_API_TOKEN", None)
            response = self.update(self.sessions[0])
        self.assertEqual(response.status_code, 503)

    def test_state_is_separated_by_session(self):
        first, second = self.sessions[:2]
        self.update(first)
        response = self.client.get(
            "/api/minecraft/state",
            params={"session_id": str(second)},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(response.json()["status"], "missing")
        self.assertIsNone(response.json()["state"])

    def test_out_of_order_updates_cannot_overwrite_newer_state(self):
        session_id = self.sessions[0]
        source_id = str(uuid4())
        newer = game_state(x=200.0)
        older = game_state(x=100.0)

        accepted = self.client.post(
            "/api/minecraft/update",
            headers=AUTH_HEADERS,
            json={"session_id": str(session_id), "source_id": source_id, "sequence": 20, "state": newer},
        )
        rejected = self.client.post(
            "/api/minecraft/update",
            headers=AUTH_HEADERS,
            json={"session_id": str(session_id), "source_id": source_id, "sequence": 19, "state": older},
        )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(rejected.status_code, 409)
        result = self.client.get(
            "/api/minecraft/state",
            params={"session_id": str(session_id)},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(result.json()["state"]["x"], 200.0)

    def test_legacy_update_cannot_overwrite_sequenced_stage_four_state(self):
        session_id = self.sessions[0]
        source_id = str(uuid4())
        sequenced = self.client.post(
            "/api/minecraft/update",
            headers=AUTH_HEADERS,
            json={"session_id": str(session_id), "source_id": source_id, "sequence": 10, "state": game_state(x=10.0)},
        )
        legacy = self.update(session_id, game_state(x=1.0))
        self.assertEqual(sequenced.status_code, 200)
        self.assertEqual(legacy.status_code, 409)

    def test_clear_keeps_sequence_watermark_against_delayed_updates(self):
        session_id = self.sessions[0]
        source_id = str(uuid4())
        payload = {
            "session_id": str(session_id),
            "source_id": source_id,
            "sequence": 10,
            "state": game_state(),
        }
        self.assertEqual(self.client.post("/api/minecraft/update", headers=AUTH_HEADERS, json=payload).status_code, 200)
        self.assertEqual(self.client.post("/api/clear", json={"session_id": str(session_id)}).status_code, 200)
        payload["sequence"] = 9
        self.assertEqual(self.client.post("/api/minecraft/update", headers=AUTH_HEADERS, json=payload).status_code, 409)
        payload["sequence"] = 11
        self.assertEqual(self.client.post("/api/minecraft/update", headers=AUTH_HEADERS, json=payload).status_code, 200)

    def test_sse_stream_sends_initial_state_and_new_updates(self):
        session_id = self.sessions[0]
        ticket_response = self.issue_event_ticket(session_id)
        self.assertEqual(ticket_response.status_code, 200)
        ticket = ticket_response.json()["ticket"]
        with self.client.stream(
            "GET",
            "/api/minecraft/events",
            params={"ticket": ticket},
        ) as response:
            self.assertEqual(response.status_code, 200)
            lines = iter(response.iter_lines())
            initial = next(line for line in lines if line.startswith("data: "))
            self.assertEqual(json.loads(initial[6:])["status"], "missing")

            self.update(session_id, game_state(player_username="LiveAlex"))
            first_update = next(line for line in lines if line.startswith("data: "))
            self.assertEqual(json.loads(first_update[6:])["state"]["player_username"], "LiveAlex")

            self.update(session_id, game_state(player_username="NewestAlex", x=22.0))
            second_update = next(line for line in lines if line.startswith("data: "))
            delivered = json.loads(second_update[6:])
            self.assertEqual(delivered["state"]["player_username"], "NewestAlex")
            self.assertEqual(delivered["state"]["x"], 22.0)

    def test_event_ticket_requires_same_origin_and_rejects_tampering(self):
        denied = self.issue_event_ticket(self.sessions[0], headers={"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(denied.status_code, 403)
        ticket = self.issue_event_ticket(self.sessions[0]).json()["ticket"]
        tampered = self.client.get("/api/minecraft/events", params={"ticket": ticket + "x"})
        self.assertEqual(tampered.status_code, 401)

    def test_sse_subscriber_limit_is_global_and_cleanup_frees_capacity(self):
        async def exercise():
            store = MinecraftStateStore()
            with patch.object(MinecraftStateStore, "MAX_SUBSCRIBERS_TOTAL", 1):
                queue = await store.subscribe(self.sessions[0])
                with self.assertRaises(RuntimeError):
                    await store.subscribe(self.sessions[1])
                store.unsubscribe(self.sessions[0], queue)
                next_queue = await store.subscribe(self.sessions[1])
                store.unsubscribe(self.sessions[1], next_queue)

        asyncio.run(exercise())

    def test_development_test_mode_is_disabled_by_default(self):
        response = self.client.get("/api/health")
        self.assertFalse(response.json()["minecraft_dev_test_mode"])
        ticket = self.client.post(
            "/api/minecraft/dev-ticket",
            headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
            json={"session_id": str(self.sessions[0])},
        )
        self.assertEqual(ticket.status_code, 404)

    def test_development_fixtures_are_labeled_and_cannot_replace_real_state(self):
        session_id = self.sessions[0]
        source_id = str(uuid4())
        environment = patch.dict(os.environ, {"JARVIS_ENV": "development", "MINECRAFT_DEV_TEST_MODE": "true"})
        with environment:
            ticket_response = self.issue_event_ticket(session_id)
            self.assertEqual(ticket_response.status_code, 200)
            dev_ticket = self.client.post(
                "/api/minecraft/dev-ticket",
                headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
                json={"session_id": str(session_id)},
            ).json()["ticket"]
            headers = {"X-Jarvis-Dev-Ticket": dev_ticket}
            update = self.client.post(
                "/api/minecraft/dev-update",
                headers=headers,
                json={"session_id": str(session_id), "source_id": source_id, "sequence": 1, "step": 0},
            )
            self.assertEqual(update.status_code, 200)
            current = self.client.get(
                "/api/minecraft/state",
                params={"session_id": str(session_id)},
                headers=AUTH_HEADERS,
            ).json()
            self.assertTrue(current["test_mode"])
            self.assertEqual(current["state"]["player_username"], "JarvisTest")
            prompt = jarvis.minecraft_prompt_context(session_id)
            self.assertIn("DEVELOPMENT TEST FIXTURE, NOT REAL GAME STATE", prompt)
            next_update = self.client.post(
                "/api/minecraft/dev-update",
                headers=headers,
                json={"session_id": str(session_id), "source_id": source_id, "sequence": 2, "step": 1},
            )
            self.assertEqual(next_update.status_code, 200)
            current = self.client.get(
                "/api/minecraft/state",
                params={"session_id": str(session_id)},
                headers=AUTH_HEADERS,
            ).json()
            self.assertEqual(current["state"]["x"], 8.5)
            self.assertEqual(current["state"]["biome"], "minecraft:forest")

            real_session = self.sessions[1]
            real_update = self.update(real_session, game_state(player_username="ActualPlayer"))
            self.assertEqual(real_update.status_code, 200)
            real_ticket = self.client.post(
                "/api/minecraft/dev-ticket",
                headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
                json={"session_id": str(real_session)},
            ).json()["ticket"]
            conflict = self.client.post(
                "/api/minecraft/dev-update",
                headers={"X-Jarvis-Dev-Ticket": real_ticket},
                json={"session_id": str(real_session), "source_id": str(uuid4()), "sequence": 1, "step": 0},
            )
            self.assertEqual(conflict.status_code, 409)
            preserved = self.client.get(
                "/api/minecraft/state",
                params={"session_id": str(real_session)},
                headers=AUTH_HEADERS,
            ).json()
            self.assertFalse(preserved["test_mode"])
            self.assertEqual(preserved["state"]["player_username"], "ActualPlayer")

            cleared = self.client.post(
                "/api/minecraft/dev-clear",
                headers={"X-Jarvis-Dev-Ticket": dev_ticket},
                json={"session_id": str(session_id), "source_id": source_id, "sequence": 3},
            )
            self.assertEqual(cleared.status_code, 200)
            self.assertEqual(self.client.get(
                "/api/minecraft/state",
                params={"session_id": str(session_id)},
                headers=AUTH_HEADERS,
            ).json()["status"], "missing")

    def test_missing_and_stale_state_are_reported(self):
        session_id = self.sessions[0]
        missing = self.client.get(
            "/api/minecraft/state",
            params={"session_id": str(session_id)},
            headers=AUTH_HEADERS,
        ).json()
        self.assertEqual(missing["status"], "missing")
        self.assertFalse(missing["available"])

        state = MinecraftGameState.model_validate(game_state())
        old_time = datetime.now(timezone.utc) - timedelta(seconds=MINECRAFT_STATE_STALE_AFTER_SECONDS + 1)
        minecraft_state_store.update(session_id, state, updated_at=old_time)
        stale = self.client.get(
            "/api/minecraft/state",
            params={"session_id": str(session_id)},
            headers=AUTH_HEADERS,
        ).json()
        self.assertEqual(stale["status"], "stale")
        self.assertTrue(stale["stale"])

    def test_latest_minecraft_context_is_added_to_every_gemini_turn(self):
        session_id = self.sessions[0]
        self.update(session_id)
        fake_client = Mock()
        fake_client.models.generate_content.return_value = SimpleNamespace(text="Your health is 18.")
        request = jarvis.ChatRequest(session_id=str(session_id), message="How much health do I have in Minecraft?")

        with patch.object(jarvis, "_client", fake_client), patch.object(jarvis, "MODEL_NAME", "gemini-2.5-flash"):
            jarvis.chat(request)

        prompt = fake_client.models.generate_content.call_args.kwargs["config"].system_instruction
        self.assertIn("Fabric state (latest)", prompt)
        self.assertIn('"health":18.0', prompt)

        other_request = jarvis.ChatRequest(session_id=str(self.sessions[1]), message="Tell me a joke.")
        with patch.object(jarvis, "_client", fake_client), patch.object(jarvis, "MODEL_NAME", "gemini-2.5-flash"):
            jarvis.chat(other_request)
        other_prompt = fake_client.models.generate_content.call_args.kwargs["config"].system_instruction
        self.assertIn("Fabric game state is unavailable", other_prompt)
        self.assertNotIn('"player_username":"Alex"', other_prompt)

    def test_new_update_is_used_on_next_turn_without_calling_gemini_for_update(self):
        session_id = self.sessions[0]
        self.update(session_id, game_state(health=18.0))
        fake_client = Mock()
        fake_client.models.generate_content.side_effect = [
            SimpleNamespace(text="First answer."),
            SimpleNamespace(text="Second answer."),
        ]
        with patch.object(jarvis, "_client", fake_client), patch.object(jarvis, "MODEL_NAME", "gemini-2.5-flash"):
            jarvis.chat(jarvis.ChatRequest(session_id=str(session_id), message="Where am I?"))
            self.update(session_id, game_state(health=6.0))
            self.assertEqual(fake_client.models.generate_content.call_count, 1)
            jarvis.chat(jarvis.ChatRequest(session_id=str(session_id), message="What should I do next?"))

        second_prompt = fake_client.models.generate_content.call_args_list[1].kwargs["config"].system_instruction
        self.assertIn('"health":6.0', second_prompt)
        self.assertIn("Fabric state (latest)", second_prompt)

    def test_missing_minecraft_context_tells_gemini_not_to_invent(self):
        fake_client = Mock()
        fake_client.models.generate_content.return_value = SimpleNamespace(text="I am not connected to the game yet.")
        request = jarvis.ChatRequest(session_id=str(self.sessions[0]), message="Where am I in Minecraft?")

        with patch.object(jarvis, "_client", fake_client), patch.object(jarvis, "MODEL_NAME", "gemini-2.5-flash"):
            jarvis.chat(request)

        prompt = fake_client.models.generate_content.call_args.kwargs["config"].system_instruction
        self.assertIn("Fabric game state is unavailable", prompt)
        self.assertIn("never invent", prompt)

    def test_stale_minecraft_context_is_marked_as_last_reported(self):
        session_id = self.sessions[0]
        state = MinecraftGameState.model_validate(game_state())
        old_time = datetime.now(timezone.utc) - timedelta(seconds=MINECRAFT_STATE_STALE_AFTER_SECONDS + 1)
        minecraft_state_store.update(session_id, state, updated_at=old_time)
        fake_client = Mock()
        fake_client.models.generate_content.return_value = SimpleNamespace(text="That is the last reported state.")
        request = jarvis.ChatRequest(session_id=str(session_id), message="Tell me my Minecraft health.")

        with patch.object(jarvis, "_client", fake_client), patch.object(jarvis, "MODEL_NAME", "gemini-2.5-flash"):
            jarvis.chat(request)

        prompt = fake_client.models.generate_content.call_args.kwargs["config"].system_instruction
        self.assertIn("Fabric state (stale last-reported)", prompt)


if __name__ == "__main__":
    unittest.main()