import { AudioCapture } from "../audio/capture.js";
import { PlaybackQueue } from "../audio/playback.js";
import { bytesFromBase64 } from "../audio/pcm16.js";
import { getState, subscribe, updateState } from "../state.js";

export class CallRoom extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.capture = null;
    this.playback = new PlaybackQueue();
    this.eventLog = null;
    this.participantList = null;
    this.unsubscribe = null;
  }

  connectedCallback() {
    this.render();
    this.unsubscribe = subscribe(() => this.sync());
    this.sync();
  }

  disconnectedCallback() {
    if (this.unsubscribe) {
      this.unsubscribe();
    }
  }

  sync() {
    const { callCode, participantId, connection } = getState();
    this.participantList?.setParticipants(participantId ? [participantId] : []);
    if (callCode && participantId && !connection) {
      this.connect(callCode, participantId);
    }
  }

  connect(callCode, participantId) {
    const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/participant?call_code=${encodeURIComponent(
      callCode,
    )}&participant_id=${encodeURIComponent(participantId)}`;
    const socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => {
      this.eventLog?.addEvent(`Joined call ${callCode}`);
      this.capture = new AudioCapture({
        onAudioFrame: (payload) => socket.send(JSON.stringify({ type: "audio", ...payload })),
        onMetadata: (payload) => socket.send(JSON.stringify({ type: "audio_metadata", ...payload })),
      });
      this.capture.start();
    });

    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        this.handleInbound(payload);
      } catch (err) {
        this.eventLog?.addEvent("Received non-JSON message");
      }
    });

    socket.addEventListener("close", () => {
      this.eventLog?.addEvent("Disconnected from call");
      this.capture?.stop();
      this.capture = null;
      updateState({ connection: null });
    });

    updateState({ connection: socket });
  }

  handleInbound(payload) {
    if (payload.kind === "AudioData" && payload.audioData?.data) {
      const bytes = bytesFromBase64(payload.audioData.data);
      this.playback.enqueue(bytes);
      return;
    }

    if (payload.type === "translation.text_delta") {
      this.eventLog?.addEvent(`Text: ${payload.delta || ""}`);
      return;
    }

    this.eventLog?.addEvent(`Event: ${payload.kind || payload.type || "message"}`);
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        .room {
          background: #10141a;
          border-radius: 12px;
          padding: 16px;
          display: grid;
          gap: 12px;
        }
        h2 { margin: 0; }
        .info { display: flex; gap: 16px; }
      </style>
      <div class="room">
        <h2>Call room</h2>
        <div class="info">
          <div>
            <h3>Participants</h3>
            <participant-list></participant-list>
          </div>
          <div>
            <h3>Event log</h3>
            <event-log></event-log>
          </div>
        </div>
      </div>
    `;

    this.eventLog = this.shadowRoot.querySelector("event-log");
    this.participantList = this.shadowRoot.querySelector("participant-list");
  }
}

customElements.define("call-room", CallRoom);
