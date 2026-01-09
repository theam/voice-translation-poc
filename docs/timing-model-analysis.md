# Timing model analysis (production test harness)

## Step A — Timestamp inventory

| Token | Locations | What it represents | Monotonicity / drift notes |
| --- | --- | --- | --- |
| `arrival_ms` | Calculated in `ScenarioEngine._listen` and stored on `ProtocolEvent.arrival_ms` and `raw["_arrival_ms"]` (`production/scenario_engine/engine.py`). | Wall-clock milliseconds since scenario start (clock `now_ms() - started_at_ms`). Not scaled by `time_acceleration`. | Monotonic as long as `Clock.time_fn` (default `time.monotonic`) is monotonic. Diverges from scenario time when acceleration > 1 because sleeps shrink but `now_ms` is unscaled. |
| `_arrival_ms` | Added to inbound raw message for debugging (`ScenarioEngine._listen`). | Same as `arrival_ms`, used only for traceability. | Same behavior as `arrival_ms`. |
| `timestamp_ms` (outbound payload) | Outbound audio frames use scenario timeline `send_at` when building ACS messages (`turn_processors/audio.py`, `_stream_silence_until`). | Scenario media timeline in ms; encoded as ISO string in the payload via `_iso_timestamp`. | Deterministic based on scenario definitions and chunking; advances independently of wall clock speed/acceleration. |
| `timestamp_ms` (inbound events) | Parsed from inbound payload (e.g., ISO timestamps in AudioData handler) into `ProtocolEvent.timestamp_ms`. Defaulted to `arrival_ms` in `_listen` for non-audio. | Depends on SUT payload; may be absolute epoch or service-relative. When absent, falls back to wall-clock arrival. | Can jump if service sends absolute epoch or its own relative clock; may be `None`. |
| `CollectedEvent.timestamp_ms` | Set in `_listen` when events are recorded. Audio uses the playout start returned by `ArrivalQueueAssembler`; text uses `arrival_ms` or raw timestamp. | Mix of arrival-gated audio placement and arrival time (text). | Audio values depend on per-stream playhead + arrival; text values follow arrival clock. |
| `turn.start_at_ms` | Scenario definition (`ScenarioTurn`) and orchestration in `_play_scenario`. | Scenario media timeline start for each turn. | Fixed per scenario file. |
| `current_time` | ScenarioEngine orchestrator variable and parameter to turn processors (`engine.py`, `turn_processors/*`). | Scenario media clock cursor as the engine advances through silence and turns. | Moves in scenario time, not wall clock; advanced by chunk timestamps, not `Clock.now_ms`. |
| `FRAME_DURATION_MS` | Constant 20 ms in `production/acs_emulator/media_engine.py`; used by silence/audio chunkers and sleeps. | Canonical frame size for outbound streaming and sleep cadence. | Fixed constant; pacing depends on `Clock.sleep` (affected by acceleration). |
| `self._media_time_ms` | ScenarioEngine field updated after silence and each turn (`engine.py`). | Snapshot of scenario media timeline (same domain as `current_time`). | Monotonic within a run; not consumed by inbound path today. |
| `ConversationManager.latest_outgoing_media_ms` | Updated via `register_outgoing_media` from silence and audio sends. | Scenario media clock for most recent outbound media frame. Used as `media_now_ms` input to playout scheduling. | Monotonic increasing with outbound scenario timestamps; lags future scheduled audio. |
| `playout_assembler.add_chunk` | Consumes `arrival_ms` and `media_now_ms`, returns `start_ms`/`duration_ms` for inbound audio (`capture/playout_assembler.py`). | Computes playout start as `max(media_now_ms + initial_buffer_ms, next_playout_ms)` per stream. Ignores arrival except for logging/clamping when media clock regresses. | Monotonic per stream via `next_playout_ms`; can be far behind or ahead of arrival depending on media clock. |
| `ConversationTape.add_pcm` | Called for outbound silence, outbound audio, and inbound scheduled audio (`ConversationTape`). | Records PCM segment at provided `start_ms`; tape normalizes so earliest segment becomes t=0 when rendering. | Accepts whatever timeline caller uses (mix of scenario timeline and playout start). |

## Step B — Outbound audio path (scenario-driven)

Call graph and flow:

```
ScenarioEngine.run
  -> _play_scenario(timeline sorted by turn.start_at_ms)
    -> _stream_silence_until(current_time, turn.start_at_ms)
         async_stream_silence yields MediaFrame(timestamp_ms=current_time+offset)
         build_audio_message(timestamp_ms=frame.timestamp_ms [scenario timeline])
         ws.send_json(...)
         tape.add_pcm(frame.timestamp_ms)
         conversation_manager.register_outgoing_media(frame.timestamp_ms)
         clock.sleep(FRAME_DURATION_MS)
    -> turn processor (AudioTurnProcessor for play_audio)
         async_chunk_audio -> offset_ms
         send_at = turn.start_at_ms + offset_ms (scenario timeline)
         build_audio_message(timestamp_ms=send_at)
         conversation_manager.register_outgoing(turn.id, ..., timestamp_ms=send_at)
         tape.add_pcm(send_at)
         clock.sleep(FRAME_DURATION_MS)
```

Outbound timeline answers:

- Frames (audio and silence) are always placed using the scenario timeline (`send_at` or silence frame timestamp). No wall-clock timestamps are used for placement. (`production/scenario_engine/engine.py`; `turn_processors/audio.py`).
- Silence is recorded into the tape with scenario timestamps and advances `latest_outgoing_media_ms` through `register_outgoing_media`, so inbound scheduling sees silence as time passing.
- Silence does **not** call `register_outgoing` because no ACS message object is created; only the media clock is advanced.

## Step C — Inbound audio path (arrival + scheduling)

Call graph and flow:

```
ScenarioEngine._listen (ws.iter_messages)
  arrival_ms = clock.now_ms() - started_at_ms  # wall clock
  protocol_event = adapter.decode_inbound(...)
  if translated_audio:
     start_ms, duration_ms = arrival_queue.add_chunk(
         stream_key, arrival_ms=arrival_ms, pcm_bytes=payload
     )
     timestamp_ms = start_ms
     tape.add_pcm(start_ms, payload)
  else:
     timestamp_ms = arrival_ms (or raw timestamp)
  collected = CollectedEvent(timestamp_ms=timestamp_ms, ...)
  collector.add(collected)
  conversation_manager.register_incoming(collected)
```

Inbound timeline answers:

- `timestamp_ms` for inbound audio is **the arrival-gated playout start** from `ArrivalQueueAssembler`, not the wall-clock arrival and not the service-provided timestamp.
- `ArrivalQueueAssembler` uses `arrival_ms` plus a per-stream playhead; it does not depend on outbound media clocks.
- Each stream’s playhead only moves forward by chunk duration, so inbound cannot be scheduled before its arrival, but can overlap outbound naturally.

## Step D — Log validation (loopback run, no logic changes)

Command: `TRANSLATION_TIME_ACCELERATION=10 python - <<'PY' ...` running `patient_correction_barge_in.yaml` with `scenario.websocket_client="loopback"`. Key observations from the run:

| Turn | Last outbound timestamp_ms (scenario) | First inbound audio timestamp_ms (from playout) | arrival_ms of first inbound | Observed audio latency (ConversationManager) |
| --- | --- | --- | --- | --- |
| `patient_initial_statement` | 14,000 ms | 80 ms | 7 ms | -13,920 ms |
| `patient_correction` | 33,180 ms | 22,080 ms | 2,486 ms | -11,100 ms |

Evidence from logs shows inbound audio scheduled near the beginning of each turn (buffered from the current media clock) while outbound keeps streaming thousands of milliseconds more, yielding negative latency and inbound audio preceding outbound completion.【7603e8†L18-L41】

Artifacts from the run live under `reports/None_2025-12-26_15-20-23/patient_correction_barge_in/` (conversation tape, raw logs, metrics) for deeper inspection.

## Step E — Intended emulation model vs. current behavior

Intended model (per docs and usage expectations):
- Full-duplex call where inbound can overlap outbound, but inbound audio cannot be heard before it arrives.
- Arrival time should cap the earliest audible time; playout should queue per stream to avoid “faster than real-time” playback.
- Outbound silence generation is the clock that lets inbound arrivals land on a realistic timeline and feeds latency metrics.

Current implementation gaps:
- Outbound timeline is purely scenario-driven; inbound scheduling is now arrival-gated per stream, independent of outbound clock, reducing “time travel” risk.
- Metrics and turn assignment still mix timelines (scenario for outbound, arrival-gated for inbound); this hybrid can still show overlap but no longer schedules audio before arrival.
- Arrival-gated playhead removes dependency on outbound cursor, so long turns with early inbound replies no longer compress or precede arrival.

## Step F — Recommended single timestamp model (proposal only)

Adopt an **arrival-gated queue model**:

- **Playout rule**: For each stream, track a playout cursor initialized to 0; set `start_ms = max(arrival_ms, cursor, media_playhead_if_needed)` and advance cursor by chunk duration. This keeps audio from playing before it arrives and respects per-stream ordering without depending on outbound progress guesses.
- **Event timestamps**: Use the same `start_ms` for ConversationTape placement, `CollectedEvent.timestamp_ms`, and turn assignment. Text events should also use `arrival_ms` or the same gating rule to keep metrics on one timeline.
- **Media clock usage**: Outbound scenario timeline stays for send scheduling, but inbound scheduling should prefer arrival-gated cursor. If keeping a tie to media progression is desired, use `media_now_ms` only as an upper bound (never earlier than arrival).

Pros/cons:
- QA audio review: Prevents inbound audio from appearing before it could be heard; tape timeline matches wall-clock ordering.
- Latency metrics: First-response timestamps reflect when audio became audible (arrival-gated), eliminating negative values and making measurements comparable across different chunk sizes or accelerations.
- Chunking differences: Queue model naturally handles variable chunk sizes because each chunk advances the playhead by its duration, independent of outbound pacing.
- Simplicity: Removes dual-timeline reasoning; inbound scheduling depends on a single monotonic playhead per stream and arrival time.

Files/classes to update in the next step:
    - `capture/arrival_queue_assembler.py` — arrival-gated scheduling per stream (implemented).
    - `scenario_engine/engine.py::_listen` — uses arrival queue and arrival-based timestamps for audio (implemented).
    - `capture/conversation_manager.py` — ensure latency and gap calculations use the unified timeline; consider storing arrival timestamps for metrics if needed.
    - `capture/conversation_tape.py` — verify tape placement matches the chosen timestamp source (no mix of scenario and arrival domains).
