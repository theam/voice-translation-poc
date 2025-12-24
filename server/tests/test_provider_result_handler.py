import asyncio
import base64
import unittest

from server.core.event_bus import EventBus, HandlerConfig
from server.core.queues import OverflowPolicy
from server.gateways.base import HandlerSettings
from server.gateways.provider_result import ProviderResultHandler
from server.models.messages import ProviderOutputEvent


class TestProviderResultHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.acs_outbound_bus = EventBus("test_out")
        self.published = []
        await self.acs_outbound_bus.register_handler(
            HandlerConfig(
                name="capture",
                queue_max=100,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1,
            ),
            self._capture,
        )
        session_metadata = {"acs_audio": {"format": {"frame_bytes": 2, "sample_rate_hz": 16000, "channels": 1}}}
        self.handler = ProviderResultHandler(
            HandlerSettings(name="provider_result", queue_max=10, overflow_policy="DROP_OLDEST"),
            acs_outbound_bus=self.acs_outbound_bus,
            translation_settings={},
            session_metadata=session_metadata,
        )

    async def asyncTearDown(self) -> None:
        await self.acs_outbound_bus.shutdown()

    async def _capture(self, payload):
        self.published.append(payload)

    async def test_audio_delta_rechunks_using_frame_size(self):
        audio_bytes = b"abcd"  # 4 bytes -> two frames when frame_bytes=2
        event = ProviderOutputEvent(
            commit_id="c1",
            session_id="s1",
            participant_id="p1",
            event_type="audio.delta",
            payload={
                "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
                "seq": 1,
                "format": {"sample_rate_hz": 16000, "channels": 1, "encoding": "pcm16"},
            },
            provider="mock",
            stream_id="stream-1",
        )

        await self.handler.handle(event)
        await asyncio.sleep(0.05)

        audio_payloads = [p for p in self.published if p.get("kind") == "audioData"]
        self.assertEqual(2, len(audio_payloads))
        decoded_frames = [base64.b64decode(p["audioData"]["data"]) for p in audio_payloads]
        self.assertIn(b"ab", decoded_frames)
        self.assertIn(b"cd", decoded_frames)

    async def test_audio_done_flushes_remainder(self):
        self.published.clear()
        audio_bytes = b"abc"  # 3 bytes => one full frame + one remainder
        delta = ProviderOutputEvent(
            commit_id="c2",
            session_id="s1",
            participant_id="p1",
            event_type="audio.delta",
            payload={"audio_b64": base64.b64encode(audio_bytes).decode("ascii"), "seq": 1, "format": {}},
            provider="mock",
            stream_id="stream-2",
        )
        done = ProviderOutputEvent(
            commit_id="c2",
            session_id="s1",
            participant_id="p1",
            event_type="audio.done",
            payload={"reason": "completed"},
            provider="mock",
            stream_id="stream-2",
        )

        await self.handler.handle(delta)
        await asyncio.sleep(0.02)
        await self.handler.handle(done)
        await asyncio.sleep(0.05)

        audio_payloads = [p for p in self.published if p.get("kind") == "audioData"]
        self.assertEqual(2, len(audio_payloads))
        self.assertEqual(base64.b64decode(audio_payloads[-1]["audioData"]["data"]), b"c")

    async def test_transcript_events_emit_translation_payload(self):
        self.published.clear()
        event = ProviderOutputEvent(
            commit_id="c3",
            session_id="s1",
            participant_id="p1",
            event_type="transcript.done",
            payload={"text": "hola", "final": True},
            provider="mock",
            stream_id="stream-3",
        )

        await self.handler.handle(event)
        await asyncio.sleep(0.05)

        translation_msgs = [p for p in self.published if p["type"] == "control.test.response.text"]
        self.assertEqual(1, len(translation_msgs))
        translation = translation_msgs[0]
        self.assertEqual("hola", translation["delta"])


if __name__ == "__main__":
    unittest.main()
