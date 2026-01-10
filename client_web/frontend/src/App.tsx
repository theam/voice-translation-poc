import { useEffect, useMemo, useRef, useState } from "react";
import { createCall, fetchTestSettings, TestSettings } from "./api";
import { startCapture } from "./audio/capture";
import { createPlayback } from "./audio/playback";

const SAMPLE_RATE = 16000;
const FRAME_MS = 20;

type Participant = {
  participant_id: string;
  display_name: string;
};

type AcsEvent = {
  type: string;
  event: Record<string, unknown>;
};

function App() {
  const [settings, setSettings] = useState<TestSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [provider, setProvider] = useState<string>("");
  const [bargeIn, setBargeIn] = useState<string>("");
  const [callCode, setCallCode] = useState<string>("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState<string>("");
  const [joinError, setJoinError] = useState<string | null>(null);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [events, setEvents] = useState<AcsEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [muted, setMuted] = useState(false);
  const [playParticipantAudio, setPlayParticipantAudio] = useState(true);
  const [playServiceAudio, setPlayServiceAudio] = useState(true);

  const playback = useMemo(() => createPlayback({ sampleRate: SAMPLE_RATE, initialBufferMs: 120 }), []);
  const wsRef = useRef<WebSocket | null>(null);
  const captureRef = useRef<Awaited<ReturnType<typeof startCapture>> | null>(null);
  const pendingAudioHeader = useRef<{ source: string; participant_id?: string | null } | null>(null);

  const isJoinRoute = window.location.pathname.startsWith("/join/");
  const initialJoinCode = isJoinRoute ? window.location.pathname.split("/join/")[1] : "";

  useEffect(() => {
    fetchTestSettings()
      .then((data) => {
        setSettings(data);
        setProvider(data.providers[0] ?? "");
        setBargeIn(data.barge_in[0] ?? "");
      })
      .catch((error) => {
        setSettingsError(String(error));
      });
  }, []);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      captureRef.current?.stop();
      playback.close();
    };
  }, [playback]);

  const handleCreate = async () => {
    setCreateError(null);
    try {
      const result = await createCall(provider, bargeIn);
      setCallCode(result.call_code);
    } catch (error) {
      setCreateError(String(error));
    }
  };

  const handleJoin = async () => {
    setJoinError(null);
    if (!displayName) {
      setJoinError("Display name is required");
      return;
    }
    const joinCode = callCode || initialJoinCode;
    if (!joinCode) {
      setJoinError("Call code is required");
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${protocol}://${window.location.host}/ws/participant`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = async () => {
      ws.send(JSON.stringify({ type: "join", call_code: joinCode, display_name: displayName }));
      ws.send(
        JSON.stringify({
          type: "audio.start",
          format: { codec: "pcm16", sample_rate_hz: SAMPLE_RATE, channels: 1, frame_ms: FRAME_MS }
        })
      );
      captureRef.current = await startCapture({
        sampleRate: SAMPLE_RATE,
        frameMs: FRAME_MS,
        onFrame: (frame) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(frame);
          }
        },
        onLevel: setMicLevel
      });
      captureRef.current.setMuted(muted);
      setConnected(true);
    };

    ws.onclose = () => {
      setConnected(false);
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        const payload = JSON.parse(event.data);
        if (payload.type === "participant.joined") {
          setParticipants((prev) => {
            if (prev.find((item) => item.participant_id === payload.participant_id)) {
              return prev;
            }
            return [...prev, { participant_id: payload.participant_id, display_name: payload.display_name }];
          });
        }
        if (payload.type === "participant.left") {
          setParticipants((prev) => prev.filter((item) => item.participant_id !== payload.participant_id));
        }
        if (payload.type === "acs.event") {
          setEvents((prev) => [{ type: payload.type, event: payload.event }, ...prev].slice(0, 200));
        }
        if (payload.type === "audio.play") {
          pendingAudioHeader.current = payload;
        }
        if (payload.type === "error") {
          setJoinError(payload.message ?? "Join failed");
        }
      } else if (event.data instanceof ArrayBuffer) {
        const header = pendingAudioHeader.current;
        if (!header) {
          return;
        }
        if (header.source === "participant" && !playParticipantAudio) {
          pendingAudioHeader.current = null;
          return;
        }
        if (header.source === "service" && !playServiceAudio) {
          pendingAudioHeader.current = null;
          return;
        }
        const sourceKey = header.source === "participant"
          ? `participant:${header.participant_id ?? "unknown"}`
          : "service";
        playback.enqueue(sourceKey, event.data);
        pendingAudioHeader.current = null;
      }
    };

    wsRef.current = ws;
  };

  const handleMuteToggle = () => {
    const nextMuted = !muted;
    setMuted(nextMuted);
    captureRef.current?.setMuted(nextMuted);
    wsRef.current?.send(JSON.stringify({ type: "mute", muted: nextMuted }));
  };

  if (!isJoinRoute) {
    return (
      <div style={{ fontFamily: "sans-serif", padding: "2rem", maxWidth: "720px" }}>
        <h1>ACS Emulator Web Client</h1>
        {settingsError && <p style={{ color: "crimson" }}>{settingsError}</p>}
        {!settings && <p>Loading test settings...</p>}
        {settings && (
          <div style={{ display: "grid", gap: "1rem" }}>
            <label>
              Provider
              <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                {settings.providers.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Barge In
              <select value={bargeIn} onChange={(event) => setBargeIn(event.target.value)}>
                {settings.barge_in.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <button onClick={handleCreate}>Create Call</button>
            {createError && <p style={{ color: "crimson" }}>{createError}</p>}
            {callCode && (
              <div>
                <p>Call code: <strong>{callCode}</strong></p>
                <a href={`/join/${callCode}`}>Join link</a>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ fontFamily: "sans-serif", padding: "2rem", maxWidth: "960px" }}>
      <h1>Join Call</h1>
      <p>Call code: <strong>{callCode || initialJoinCode}</strong></p>
      {!connected && (
        <div style={{ display: "grid", gap: "1rem", maxWidth: "420px" }}>
          <label>
            Display name
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          </label>
          <label>
            Call code
            <input value={callCode || initialJoinCode} onChange={(event) => setCallCode(event.target.value)} />
          </label>
          <button onClick={handleJoin}>Join</button>
          {joinError && <p style={{ color: "crimson" }}>{joinError}</p>}
        </div>
      )}
      {connected && (
        <div style={{ display: "grid", gap: "1rem" }}>
          <div style={{ display: "flex", gap: "1rem" }}>
            <button onClick={handleMuteToggle}>{muted ? "Unmute" : "Mute"}</button>
            <label>
              <input
                type="checkbox"
                checked={playParticipantAudio}
                onChange={(event) => setPlayParticipantAudio(event.target.checked)}
              />
              Play participant audio
            </label>
            <label>
              <input
                type="checkbox"
                checked={playServiceAudio}
                onChange={(event) => setPlayServiceAudio(event.target.checked)}
              />
              Play service audio
            </label>
          </div>
          <p>Mic level: {micLevel.toFixed(3)}</p>
          <section>
            <h2>Participants</h2>
            <ul>
              {participants.map((participant) => (
                <li key={participant.participant_id}>
                  {participant.display_name} ({participant.participant_id})
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2>ACS Events</h2>
            <div style={{ maxHeight: "300px", overflow: "auto", background: "#f5f5f5", padding: "0.5rem" }}>
              {events.map((event, index) => (
                <pre key={index} style={{ whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(event.event, null, 2)}
                </pre>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
