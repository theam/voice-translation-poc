import asyncio
import unittest
from unittest.mock import MagicMock

from server.gateways.acs.audio_metadata import AudioMetadataHandler
from server.models.gateway_input_event import GatewayInputEvent

class TestAudioMetadataHandler(unittest.TestCase):

    def setUp(self):
        self.session_metadata = {}
        self.handler = AudioMetadataHandler(self.session_metadata)

    def test_handle_audio_metadata(self):
        envelope = MagicMock(spec=GatewayInputEvent)
        envelope.event_id = "test-msg-id"
        envelope.session_id = "session-1"
        envelope.received_at_utc = "2024-01-01T00:00:00Z"
        envelope.payload = {
            "kind": "audiometadata",
            "audiometadata": {
                "subscriptionId": "sub-123",
                "encoding": "PCM",
                "sampleRate": 24000,
                "channels": 1,
                "length": 640,
            },
        }

        asyncio.run(self.handler.handle(envelope))

        self.assertIn("acs_audio", self.session_metadata)
        fmt = self.session_metadata["acs_audio"]["format"]
        self.assertEqual(fmt["encoding"], "pcm16")
        self.assertEqual(fmt["sample_rate_hz"], 24000)
        self.assertEqual(fmt["channels"], 1)
        self.assertEqual(fmt["frame_bytes"], 640)

    def test_handle_empty_payload(self):
        envelope = MagicMock(spec=GatewayInputEvent)
        envelope.event_id = "test-msg-id-3"
        envelope.session_id = "session-1"
        envelope.received_at_utc = "2024-01-01T00:00:00Z"
        envelope.payload = {}

        self.session_metadata = {} # Reset
        self.handler = AudioMetadataHandler(self.session_metadata)

        asyncio.run(self.handler.handle(envelope))

        self.assertNotIn("acs_audio", self.session_metadata)

if __name__ == '__main__':
    unittest.main()
