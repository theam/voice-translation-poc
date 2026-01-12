import { AudioCapture } from "../audio/capture.js";
import { MultiParticipantAudioManager } from "../audio/multi-participant-manager.js";
import { bytesFromBase64 } from "../audio/pcm16.js";
import { getState, subscribe, updateState } from "../state.js";

export class CallRoom extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.capture = null;
    this.audioManager = null;
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

    // Stop all audio playback queues
    if (this.audioManager) {
      this.audioManager.stopAll();
      this.audioManager = null;
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
    const connectStart = performance.now();

    // Show connecting feedback immediately
    this.eventLog?.addEvent(`Connecting to call ${callCode}...`);

    const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/participant?call_code=${encodeURIComponent(
      callCode,
    )}&participant_id=${encodeURIComponent(participantId)}`;

    const socket = new WebSocket(wsUrl);

    // Create MultiParticipantAudioManager after user interaction (joining call)
    if (!this.audioManager) {
      this.audioManager = new MultiParticipantAudioManager();
    }

    const handleOpen = async () => {
      const wsTime = performance.now() - connectStart;
      this.eventLog?.addEvent(`Connected (${wsTime.toFixed(0)}ms)`);

      // Show microphone permission request feedback
      this.eventLog?.addEvent("Requesting microphone access...");

      const captureStart = performance.now();
      // Audio is automatically resampled to 16kHz mono PCM16 (ACS standard)
      // Backend sends audio metadata to upstream after test settings
      this.capture = new AudioCapture({
        onAudioFrame: (payload) => socket.send(JSON.stringify({ type: "audio", ...payload })),
      });

      try {
        await this.capture.start();
        const captureTime = performance.now() - captureStart;
        this.eventLog?.addEvent(`Microphone ready (${captureTime.toFixed(0)}ms)`);
        this.eventLog?.addEvent(`✓ Joined call successfully`);
      } catch (err) {
        console.error("Audio capture failed:", err);
        this.eventLog?.addEvent(`✗ Microphone error: ${err.message}`);
      }
    };

    socket.addEventListener("open", handleOpen);

    // Handle race condition: if socket already connected, call handleOpen manually
    if (socket.readyState === WebSocket.OPEN) {
      handleOpen();
    }

    // Handle WebSocket errors
    socket.addEventListener("error", (event) => {
      console.error("WebSocket error:", event);
      this.eventLog?.addEvent("✗ Connection error");
    });

    socket.addEventListener("message", async (event) => {
      try {
        const payload = JSON.parse(event.data);
        await this.handleInbound(payload);
      } catch (err) {
        console.error("Message handling error:", err);
        this.eventLog?.addEvent("Received non-JSON message");
      }
    });

    socket.addEventListener("close", (event) => {
      // Distinguish between clean disconnect and connection failure
      if (event.wasClean) {
        this.eventLog?.addEvent("Disconnected from call");
      } else {
        console.error("WebSocket closed unexpectedly, code:", event.code);
        this.eventLog?.addEvent(`✗ Connection lost (code: ${event.code})`);
      }
      this.capture?.stop();
      this.capture = null;
      this.audioManager?.stopAll();
      updateState({
        connection: null,
        participants: []
      });
    });

    updateState({ connection: socket });
  }

  async handleInbound(payload) {
    // Handle connection status messages
    if (payload.type === "connection.established") {
      this.eventLog?.addEvent(payload.message || "Initializing...");
      return;
    }

    if (payload.type === "connection.ready") {
      this.eventLog?.addEvent(payload.message || "Ready");
      return;
    }

    // Handle error messages from backend
    if (payload.type === "error") {
      console.error("Backend error:", payload.message);
      this.eventLog?.addEvent(`✗ Error: ${payload.message}`);
      return;
    }

    // Handle participant list updates
    if (payload.type === "participant.list") {
      updateState({ participants: payload.participants || [] });
      return;
    }

    if (payload.type === "participant.joined") {
      this.eventLog?.addEvent(`${payload.participant_id} joined`);
      updateState({ participants: payload.participants || [] });
      return;
    }

    if (payload.type === "participant.left") {
      this.eventLog?.addEvent(`${payload.participant_id} left`);
      updateState({ participants: payload.participants || [] });

      // Clean up audio queue for participant who left
      const leftParticipantId = payload.participant_id;
      if (leftParticipantId && this.audioManager) {
        this.audioManager.removeParticipant(leftParticipantId);
      }
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

      // Extract participant ID from audio message
      const participantId = payload.audioData?.participantRawID || "unknown";

      // Warn if participant ID is missing - this should not happen
      if (participantId === "unknown") {
        console.warn("Received audio with missing participant ID. Payload structure:", {
          kind: payload.kind,
          type: payload.type,
          hasAudioData: !!payload.audioData,
          audioDataKeys: payload.audioData ? Object.keys(payload.audioData) : [],
          participantRawID: payload.audioData?.participantRawID
        });
      }

      const bytes = bytesFromBase64(base64Data);

      if (!this.audioManager) {
        console.warn("MultiParticipantAudioManager not initialized, skipping audio");
        return;
      }

      try {
        await this.audioManager.enqueueAudio(participantId, bytes);
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
