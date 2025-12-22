import asyncio
import unittest
from unittest.mock import MagicMock
from server.gateways.acs.audio_metadata import AudioMetadataHandler
from server.models.envelope import Envelope

class TestAudioMetadataHandler(unittest.TestCase):

    def setUp(self):
        self.session_metadata = {}
        self.handler = AudioMetadataHandler(self.session_metadata)

    def test_handle_audio_metadata(self):
        envelope = MagicMock(spec=Envelope)
        envelope.message_id = "test-msg-id"
        envelope.payload = {
            "encoding": "PCM",
            "sampleRate": 24000,
            "channels": 1,
            "sampleWidth": 2
        }

        asyncio.run(self.handler.handle(envelope))

        self.assertIn("audio_format", self.session_metadata)
        self.assertEqual(self.session_metadata["audio_format"]["encoding"], "PCM")
        self.assertEqual(self.session_metadata["audio_format"]["sample_rate"], 24000)
        self.assertEqual(self.session_metadata["audio_format"]["channels"], 1)
        self.assertEqual(self.session_metadata["audio_format"]["sample_width"], 2)

    def test_handle_audio_metadata_alt_keys(self):
        envelope = MagicMock(spec=Envelope)
        envelope.message_id = "test-msg-id-2"
        envelope.payload = {
            "sample_rate": 16000,
            "bitsPerSample": 16
        }

        asyncio.run(self.handler.handle(envelope))

        self.assertIn("audio_format", self.session_metadata)
        self.assertEqual(self.session_metadata["audio_format"]["sample_rate"], 16000)
        self.assertEqual(self.session_metadata["audio_format"]["sample_width"], 2)

    def test_handle_empty_payload(self):
        envelope = MagicMock(spec=Envelope)
        envelope.message_id = "test-msg-id-3"
        envelope.payload = {}
        
        self.session_metadata = {} # Reset
        self.handler = AudioMetadataHandler(self.session_metadata)

        asyncio.run(self.handler.handle(envelope))

        self.assertNotIn("audio_format", self.session_metadata)

if __name__ == '__main__':
    unittest.main()
