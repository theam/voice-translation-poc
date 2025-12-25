import asyncio
import base64
import time
import unittest

from server.core.event_bus import EventBus, HandlerConfig
from server.core.queues import OverflowPolicy
from server.gateways.base import HandlerSettings
from server.gateways.provider_result import ProviderResultHandler
from server.models.provider_events import ProviderOutputEvent


class TestProviderResultHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.acs_outbound_bus = EventBus("test_out")
        self.published = []
        self.timestamps = []
        await self.acs_outbound_bus.register_handler(
            HandlerConfig(
                name="capture",
                queue_max=100,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1,
            ),
            self._capture,
        )
        session_metadata = {
            "acs_audio": {
                "format": {
                    "frame_bytes": 640,
                    "sample_rate_hz": 16000,
                    "channels": 1,
                    "encoding": "pcm16",
                }
            }
        }
        self.handler = ProviderResultHandler(
            HandlerSettings(name="provider_result", queue_max=10, overflow_policy="DROP_OLDEST"),
            acs_outbound_bus=self.acs_outbound_bus,
            translation_settings={},
            session_metadata=session_metadata,
        )

    async def asyncTearDown(self) -> None:
        await self.acs_outbound_bus.shutdown()

    async def _capture(self, payload):
        self.timestamps.append(time.monotonic())
        self.published.append(payload)

    async def test_audio_frames_use_fixed_size_from_metadata(self):
        audio_bytes = b"a" * (640 * 3)
        delta = ProviderOutputEvent(
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
        done = ProviderOutputEvent(
            commit_id="c1",
            session_id="s1",
            participant_id="p1",
            event_type="audio.done",
            payload={"reason": "completed"},
            provider="mock",
            stream_id="stream-1",
        )

        await self.handler.handle(delta)
        await self.handler.handle(done)
        await asyncio.sleep(0.25)

        audio_payloads = [p for p in self.published if p.get("kind") == "audioData"]
        self.assertEqual(3, len(audio_payloads))
        decoded_frames = [base64.b64decode(p["audioData"]["data"]) for p in audio_payloads]
        for frame in decoded_frames:
            self.assertEqual(640, len(frame))

    async def test_audio_done_pads_final_frame(self):
        self.published.clear()
        self.timestamps.clear()
        audio_bytes = b"b" * (640 + 320)
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
        await self.handler.handle(done)
        await asyncio.sleep(0.3)

        audio_payloads = [p for p in self.published if p.get("kind") == "audioData"]
        self.assertEqual(2, len(audio_payloads))
        decoded_frames = [base64.b64decode(p["audioData"]["data"]) for p in audio_payloads]
        self.assertTrue(all(len(frame) == 640 for frame in decoded_frames))
        self.assertEqual(decoded_frames[-1][-320:], b"\x00" * 320)

    async def test_audio_frames_are_paced(self):
        self.published.clear()
        self.timestamps.clear()
        audio_bytes = b"c" * (640 * 4)
        delta = ProviderOutputEvent(
            commit_id="c3",
            session_id="s1",
            participant_id="p1",
            event_type="audio.delta",
            payload={"audio_b64": base64.b64encode(audio_bytes).decode("ascii"), "seq": 1, "format": {}},
            provider="mock",
            stream_id="stream-3",
        )
        done = ProviderOutputEvent(
            commit_id="c3",
            session_id="s1",
            participant_id="p1",
            event_type="audio.done",
            payload={"reason": "completed"},
            provider="mock",
            stream_id="stream-3",
        )

        await self.handler.handle(delta)
        await self.handler.handle(done)
        await asyncio.sleep(0.4)

        frames_with_time = [
            (payload, ts) for payload, ts in zip(self.published, self.timestamps) if payload.get("kind") == "audioData"
        ]
        self.assertEqual(4, len(frames_with_time))
        intervals = [
            frames_with_time[i + 1][1] - frames_with_time[i][1] for i in range(len(frames_with_time) - 1)
        ]
        for interval in intervals:
            self.assertGreater(interval, 0.015)
            self.assertLess(interval, 0.05)

    async def test_transcript_events_emit_translation_payload(self):
        self.published.clear()
        self.timestamps.clear()
        event = ProviderOutputEvent(
            commit_id="c4",
            session_id="s1",
            participant_id="p1",
            event_type="transcript.done",
            payload={"text": "hola", "final": True},
            provider="mock",
            stream_id="stream-4",
        )

        await self.handler.handle(event)
        await asyncio.sleep(0.05)

        translation_msgs = [p for p in self.published if p["type"] == "control.test.response.text"]
        self.assertEqual(1, len(translation_msgs))
        translation = translation_msgs[0]
        self.assertEqual("hola", translation["delta"])


if __name__ == "__main__":
    unittest.main()
