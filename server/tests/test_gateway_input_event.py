import base64
import unittest
from datetime import datetime

from server.models.gateway_input_event import ConnectionContext, GatewayInputEvent


class TestGatewayInputEvent(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = ConnectionContext(
            ingress_ws_id="ingress-1",
            call_connection_id="call-123",
            call_correlation_id="corr-456",
        )

    def test_audio_metadata_mapping(self):
        frame = {
            "kind": "audiometadata",
            "audiometadata": {
                "subscriptionId": "89e8cb59-b991-48b0-b154-1db84f16a077",
                "encoding": "PCM",
                "sampleRate": 16000,
                "channels": 1,
                "length": 640,
            },
        }

        event = GatewayInputEvent.from_acs_frame(frame, sequence=5, ctx=self.ctx)

        self.assertEqual(frame, event.payload)
        self.assertEqual("call-123", event.session_id)
        self.assertEqual("corr-456", event.trace.call_correlation_id)
        self.assertEqual(5, event.trace.sequence)
        # ISO-8601 validation
        datetime.fromisoformat(event.received_at_utc)

    def test_audio_data_mapping(self):
        audio_data = {
            "timestamp": "2024-11-15T19:16:12.925Z",
            "participantrawid": "8:acs:participant",
            "data": base64.b64encode(b"abc").decode("ascii"),
            "silent": False,
        }
        frame = {"kind": "audiodata", "audiodata": audio_data}

        event = GatewayInputEvent.from_acs_frame(frame, sequence=1, ctx=self.ctx)

        self.assertEqual(frame, event.payload)
        self.assertEqual(frame["audiodata"]["participantrawid"], event.payload["audiodata"]["participantrawid"])
        self.assertEqual("call-123", event.session_id)

    def test_unknown_kind(self):
        event = GatewayInputEvent.from_acs_frame({}, sequence=99, ctx=self.ctx)
        self.assertEqual({}, event.payload)
        self.assertEqual(99, event.trace.sequence)

if __name__ == "__main__":
    unittest.main()
