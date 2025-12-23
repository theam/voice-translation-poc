import base64
import unittest
from datetime import datetime

from server.gateways.acs.acs_input_mapper import AcsInputMapper
from server.models.gateway_input_event import ConnectionContext


class TestAcsInputMapper(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = ConnectionContext(
            ingress_ws_id="ingress-1",
            call_connection_id="call-123",
            call_correlation_id="corr-456",
        )
        self.mapper = AcsInputMapper(self.ctx)

    def test_audio_metadata_mapping(self):
        frame = {
            "kind": "AudioMetadata",
            "audiometadata": {
                "subscriptionid": "89e8cb59-b991-48b0-b154-1db84f16a077",
                "encoding": "PCM",
                "samplerate": 16000,
                "channels": 1,
                "length": 640,
            },
        }

        event = self.mapper.from_frame(frame, sequence=5)

        self.assertEqual("acs.audio.metadata", event.event_type)
        self.assertEqual(frame["audiometadata"], event.payload)
        self.assertEqual("call-123", event.session_id)
        self.assertEqual("corr-456", event.trace.call_correlation_id)
        self.assertEqual(5, event.trace.sequence)
        self.assertEqual(event.received_at_utc, event.timestamp_utc)
        self.assertEqual(
            "89e8cb59-b991-48b0-b154-1db84f16a077",
            event.subscription_id,
        )
        # ISO-8601 validation
        datetime.fromisoformat(event.received_at_utc)
        self.assertIsNone(event.participant_id)

    def test_audio_data_mapping(self):
        audio_data = {
            "timestamp": "2024-11-15T19:16:12.925Z",
            "participantrawid": "8:acs:participant",
            "data": base64.b64encode(b"abc").decode("ascii"),
            "silent": False,
        }
        frame = {"kind": "AudioData", "audiodata": audio_data}

        event = self.mapper.from_frame(frame, sequence=1)

        self.assertEqual("acs.audio.data", event.event_type)
        self.assertEqual(audio_data, event.payload)
        self.assertEqual("8:acs:participant", event.participant_id)
        self.assertEqual(audio_data["timestamp"], event.timestamp_utc)
        self.assertIsNone(event.subscription_id)
        self.assertEqual(frame, event.raw_frame)
        self.assertEqual("call-123", event.session_id)

    def test_unknown_kind(self):
        event = self.mapper.from_frame({}, sequence=99)
        self.assertEqual("acs.unknown", event.event_type)
        self.assertEqual({}, event.payload)
        self.assertEqual({}, event.raw_frame)
        self.assertEqual(99, event.trace.sequence)

    def test_invalid_base64_raises(self):
        frame = {
            "kind": "AudioData",
            "audiodata": {"data": "!!!notbase64!!!"},
        }

        with self.assertRaises(ValueError):
            self.mapper.from_frame(frame, sequence=3)

    def test_control_type_mapping(self):
        frame = {
            "type": "control.test.settings",
            "settings": {"language": "en-US"},
        }

        event = self.mapper.from_frame(frame, sequence=2)

        self.assertEqual("control.test.settings", event.event_type)
        self.assertEqual(frame, event.payload)
        self.assertEqual("call-123", event.session_id)
        self.assertEqual("corr-456", event.trace.call_correlation_id)
        self.assertEqual(2, event.trace.sequence)
        datetime.fromisoformat(event.timestamp_utc)


if __name__ == "__main__":
    unittest.main()
