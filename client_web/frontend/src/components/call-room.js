import { AudioCapture } from "../audio/capture.js";
import { PlaybackQueue } from "../audio/playback.js";
import { bytesFromBase64 } from "../audio/pcm16.js";
import { getState, subscribe, updateState } from "../state.js";

export class CallRoom extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.capture = null;
    this.playback = null;
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
    const { callCode, participantId, connection, participants } = getState();
    this.participantList?.setParticipants(participants);
    if (callCode && participantId && !connection) {
      this.connect(callCode, participantId);
    }
    this.updateHangUpButton();
  }

  updateHangUpButton() {
    const { connection } = getState();
    const button = this.shadowRoot.querySelector(".hang-up-button");
    if (button) {
      button.disabled = !connection;
      button.style.opacity = connection ? "1" : "0.5";
    }
  }

  disconnect() {
    const { connection } = getState();
    if (!connection) {
      return;
    }

    this.eventLog?.addEvent("Leaving call...");

    // Close WebSocket connection (this will trigger the close event handler)
    connection.close();

    // Stop audio capture
    if (this.capture) {
      this.capture.stop();
      this.capture = null;
    }

    // Stop audio playback
    if (this.playback) {
      this.playback.stop();
    }

    // Clear state
    updateState({
      connection: null,
      callCode: "",
      participantId: "",
      participants: []
    });
  }

  connect(callCode, participantId) {
    console.log("Connecting to call...");
    const connectStart = performance.now();

    const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/participant?call_code=${encodeURIComponent(
      callCode,
    )}&participant_id=${encodeURIComponent(participantId)}`;
    const socket = new WebSocket(wsUrl);

    // Create PlaybackQueue after user interaction (joining call)
    if (!this.playback) {
      this.playback = new PlaybackQueue();
    }

    socket.addEventListener("open", async () => {
      const wsTime = performance.now() - connectStart;
      console.log(`WebSocket connected in ${wsTime.toFixed(0)}ms`);
      this.eventLog?.addEvent(`Joined call ${callCode}`);

      const captureStart = performance.now();
      this.capture = new AudioCapture({
        onAudioFrame: (payload) => socket.send(JSON.stringify({ type: "audio", ...payload })),
        onMetadata: (payload) => socket.send(JSON.stringify({ type: "audio_metadata", ...payload })),
      });

      try {
        await this.capture.start();
        const captureTime = performance.now() - captureStart;
        console.log(`Audio capture started in ${captureTime.toFixed(0)}ms`);
        console.log(`Total connect time: ${(performance.now() - connectStart).toFixed(0)}ms`);
      } catch (err) {
        console.error("Audio capture failed:", err);
        this.eventLog?.addEvent(`Microphone error: ${err.message}`);
      }
    });

    socket.addEventListener("message", async (event) => {
      try {
        const payload = JSON.parse(event.data);
        const msgType = payload.kind || payload.type;
        console.log("Received message:", msgType, payload);
        await this.handleInbound(payload);
      } catch (err) {
        console.error("Message handling error:", err);
        this.eventLog?.addEvent("Received non-JSON message");
      }
    });

    socket.addEventListener("close", () => {
      this.eventLog?.addEvent("Disconnected from call");
      this.capture?.stop();
      this.capture = null;
      this.playback?.stop();
      updateState({
        connection: null,
        participants: []
      });
    });

    updateState({ connection: socket });
  }

  async handleInbound(payload) {
    // Handle error messages from backend
    if (payload.type === "error") {
      console.error("Backend error:", payload.message);
      this.eventLog?.addEvent(`Error: ${payload.message}`);
      return;
    }

    // Handle participant list updates
    if (payload.type === "participant.list") {
      console.log("Received participant list:", payload.participants);
      updateState({ participants: payload.participants || [] });
      return;
    }

    if (payload.type === "participant.joined") {
      console.log("Participant joined:", payload.participant_id);
      this.eventLog?.addEvent(`${payload.participant_id} joined`);
      updateState({ participants: payload.participants || [] });
      return;
    }

    if (payload.type === "participant.left") {
      console.log("Participant left:", payload.participant_id);
      this.eventLog?.addEvent(`${payload.participant_id} left`);
      updateState({ participants: payload.participants || [] });
      return;
    }

    // Check for audio data (case-insensitive)
    const kind = payload.kind?.toLowerCase();
    const type = payload.type?.toLowerCase();
    const isAudioData = (kind === "audiodata" || type === "audiodata") && (payload.audioData?.data || payload.data);

    if (isAudioData) {
      // Handle both formats: ACS protocol uses audioData.data, backend may use data directly
      const base64Data = payload.audioData?.data || payload.data;

      if (!base64Data) {
        console.warn("Audio message has no data:", payload);
        return;
      }

      const bytes = bytesFromBase64(base64Data);
      console.log(`Received audio: ${bytes.length} bytes`);

      if (!this.playback) {
        console.warn("PlaybackQueue not initialized, skipping audio");
        return;
      }

      try {
        await this.playback.enqueue(bytes);
        console.log(`Audio enqueued successfully`);
      } catch (err) {
        console.error("Playback error:", err);
        this.eventLog?.addEvent(`Playback error: ${err.message}`);
      }
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
        .header { display: flex; justify-content: space-between; align-items: center; }
        .hang-up-button {
          background: #dc3545;
          color: white;
          border: none;
          border-radius: 8px;
          padding: 10px 20px;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          transition: background 0.2s, opacity 0.2s;
        }
        .hang-up-button:hover:not(:disabled) {
          background: #c82333;
        }
        .hang-up-button:disabled {
          cursor: not-allowed;
        }
        .info { display: flex; gap: 16px; }
      </style>
      <div class="room">
        <div class="header">
          <h2>Call room</h2>
          <button class="hang-up-button" disabled>Hang Up</button>
        </div>
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

    const hangUpButton = this.shadowRoot.querySelector(".hang-up-button");
    hangUpButton.addEventListener("click", () => this.disconnect());
  }
}

customElements.define("call-room", CallRoom);
