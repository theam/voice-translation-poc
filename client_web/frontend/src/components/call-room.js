import { createPlayback } from "../audio/playback";
import { startCapture } from "../audio/capture";
import { getState, subscribe, updateState } from "../state";
import "./participant-list";
import "./event-log";

const SAMPLE_RATE = 16000;
const FRAME_MS = 20;

class CallRoom extends HTMLElement {
  constructor() {
    super();
    this.ws = null;
    this.capture = null;
    this.playback = createPlayback({ sampleRate: SAMPLE_RATE, initialBufferMs: 120 });
    this.pendingAudioHeader = null;
    this.unsubscribe = null;
  }

  connectedCallback() {
    this.unsubscribe = subscribe((state) => this.render(state));
  }

  disconnectedCallback() {
    this.unsubscribe?.();
    this.closeSession();
    this.playback.close();
  }

  setData({ routeCallCode }) {
    this.routeCallCode = routeCallCode;
  }

  async startSession({ displayName, callCode }) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return;
    }

    updateState({ participants: [], events: [] });

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${protocol}://${window.location.host}/ws/participant`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = async () => {
      ws.send(JSON.stringify({ type: "join", call_code: callCode, display_name: displayName }));
      ws.send(JSON.stringify({
        type: "audio.start",
        format: { codec: "pcm16", sample_rate_hz: SAMPLE_RATE, channels: 1, frame_ms: FRAME_MS }
      }));
      this.capture = await startCapture({
        sampleRate: SAMPLE_RATE,
        frameMs: FRAME_MS,
        onFrame: (frame) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(frame);
          }
        },
        onLevel: (level) => updateState({ micLevel: level })
      });
      this.capture.setMuted(getState().muted);
      updateState({ connected: true, joinError: null });
    };

    ws.onclose = () => {
      updateState({ connected: false });
      this.closeSession();
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        const payload = JSON.parse(event.data);
        if (payload.type === "participant.joined") {
          updateState({
            participants: dedupeParticipants(getState().participants, payload)
          });
        }
        if (payload.type === "participant.left") {
          updateState({
            participants: getState().participants.filter((item) => item.participant_id !== payload.participant_id)
          });
        }
        if (payload.type === "acs.event") {
          const next = [{ event: payload.event }, ...getState().events].slice(0, 200);
          updateState({ events: next });
        }
        if (payload.type === "audio.play") {
          this.pendingAudioHeader = payload;
        }
        if (payload.type === "error") {
          updateState({ joinError: payload.message ?? "Join failed" });
        }
      } else if (event.data instanceof ArrayBuffer) {
        const header = this.pendingAudioHeader;
        if (!header) return;
        const state = getState();
        if (header.source === "participant" && !state.playParticipantAudio) {
          this.pendingAudioHeader = null;
          return;
        }
        if (header.source === "service" && !state.playServiceAudio) {
          this.pendingAudioHeader = null;
          return;
        }
        const sourceKey = header.source === "participant"
          ? `participant:${header.participant_id || "unknown"}`
          : "service";
        this.playback.enqueue(sourceKey, event.data);
        this.pendingAudioHeader = null;
      }
    };

    this.ws = ws;
  }

  closeSession() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.capture?.stop();
    this.capture = null;
  }

  render(state) {
    if (!state) return;
    const connected = state.connected;
    this.innerHTML = `
      <section class="card column">
        <h2>Call Status</h2>
        <p>Connection: <span class="badge">${connected ? "Connected" : "Disconnected"}</span></p>
        <p class="muted">Mic level: ${state.micLevel.toFixed(3)}</p>
        <div class="row">
          <button type="button" class="toggle-mute">${state.muted ? "Unmute" : "Mute"}</button>
          <label class="toggle">
            <input type="checkbox" name="playParticipantAudio" ${state.playParticipantAudio ? "checked" : ""} />
            Play participant audio
          </label>
          <label class="toggle">
            <input type="checkbox" name="playServiceAudio" ${state.playServiceAudio ? "checked" : ""} />
            Play service audio
          </label>
        </div>
      </section>
      <div class="row">
        <participant-list></participant-list>
        <event-log></event-log>
      </div>
    `;

    this.querySelector("participant-list")?.setData(state.participants);
    this.querySelector("event-log")?.setData(state.events);

    this.querySelector("button.toggle-mute")?.addEventListener("click", () => {
      const nextMuted = !getState().muted;
      updateState({ muted: nextMuted });
      this.capture?.setMuted(nextMuted);
      this.ws?.send(JSON.stringify({ type: "mute", muted: nextMuted }));
    });

    this.querySelector("input[name='playParticipantAudio']")?.addEventListener("change", (event) => {
      updateState({ playParticipantAudio: event.target.checked });
    });

    this.querySelector("input[name='playServiceAudio']")?.addEventListener("change", (event) => {
      updateState({ playServiceAudio: event.target.checked });
    });
  }
}

function dedupeParticipants(list, payload) {
  const exists = list.find((item) => item.participant_id === payload.participant_id);
  if (exists) return list;
  return [...list, { participant_id: payload.participant_id, display_name: payload.display_name }];
}

customElements.define("call-room", CallRoom);
