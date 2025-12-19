# ConversationTape Timing Analysis

## Overview

The `ConversationTape` class creates a single audio file (`call_mix.wav`) that represents the full conversation including both outgoing (patient) audio and incoming (translated) audio. This is crucial for understanding the real user experience.

## How Timing Works

### 1. Outgoing Audio (Patient Speaking)

**Location**: `scenario_engine/turn_processors/audio.py:86`

```python
send_at = turn.start_at_ms + offset_ms
self.tape.add_pcm(send_at, data)
```

**Timing**: Uses **scenario timeline** (scheduled time)
- `turn.start_at_ms`: When the turn is scheduled to start (e.g., 0ms, 22000ms)
- `offset_ms`: Offset within the audio file (0, 100, 200, ...)
- **Result**: Audio is placed at its **scheduled position** in the tape

**Example**:
```
Turn 1 starts at: 0ms
Audio chunks added at: 0ms, 100ms, 200ms, ..., 14000ms
```

### 2. Incoming Audio (Translated Audio)

**Location**: `scenario_engine/engine.py:304`

```python
arrival_ms = self.clock.now_ms() - started_at_ms
tape.add_pcm(arrival_ms, protocol_event.audio_payload)
```

**Timing**: Uses **wall-clock arrival time** (actual time)
- `self.clock.now_ms()`: Current wall-clock time
- `started_at_ms`: When the scenario started
- `arrival_ms`: How long since scenario started
- **Result**: Audio is placed at the **actual arrival time** in the tape

**Example**:
```
Patient audio ends at: 14000ms (scheduled)
Translation arrives at: 16000ms, 16100ms, 16200ms, ... (actual)
```

## The Gap: Processing Delay

### What Creates the Gap

```
Timeline:
├─ 0ms: Patient starts speaking (scheduled)
├─ 14000ms: Patient stops speaking (scheduled)
│           ↓ [Translation processing happens here]
├─ 16000ms: First translation audio arrives (actual)
└─ 30000ms: Last translation audio arrives (actual)

Gap in tape: 14000ms - 16000ms (2 seconds of silence)
```

### Is This Correct?

**Yes!** This gap represents the **real processing delay** of the translation service:
1. Patient finishes speaking at 14s
2. Audio is sent to translation service
3. Translation service processes the audio
4. Translated audio starts arriving at 16s
5. **2-second gap = actual latency**

This is **exactly what the user would experience** in a real conversation.

## Potential Issues

### Issue 1: Timestamp Mismatch Between Systems

**Problem**: If the translation service sends timestamps in a different coordinate system:

```python
# engine.py:287-290
if raw_ts is not None and raw_ts > 1_000_000_000:
    # Service sent absolute timestamp (e.g., UNIX epoch)
    timestamp_ms = max(0, raw_ts - started_at_ms)
else:
    # Service sent relative timestamp or we use arrival time
    timestamp_ms = raw_ts if raw_ts is not None else arrival_ms
```

**Risk**: If `protocol_event.timestamp_ms` is not `None` and is a relative timestamp from the service's perspective, it might not align with the scenario timeline.

**Example of problem**:
```
Scenario starts at: wall_clock=1000000ms
Patient audio sent at: scenario_time=0ms, wall_clock=1000000ms
Service receives at: wall_clock=1000050ms (50ms network delay)
Service processes for: 1500ms
Service sends translation with timestamp: service_time=1500ms
Tape receives translation at: wall_clock=1001550ms

If service_time is used directly:
→ Tape adds audio at 1500ms (correct)

If arrival_ms is used:
→ arrival_ms = 1001550 - 1000000 = 1550ms (correct)
→ Includes 50ms network delay in processing time
```

### Issue 2: Clock Acceleration Not Applied to Incoming Audio

**Current behavior**:

```python
# Outgoing audio uses accelerated sleep
await self.clock.sleep(FRAME_DURATION_MS)  # Respects acceleration

# Incoming audio uses wall-clock time
arrival_ms = self.clock.now_ms() - started_at_ms  # No acceleration adjustment
```

**Problem**: If `acceleration=2.0` (2x speed):
- Outgoing audio plays at 2x speed
- But incoming audio timestamps are based on wall-clock time
- This can cause timing misalignment

**Example**:
```
acceleration=2.0

Outgoing audio:
├─ 0ms: Start (scheduled)
├─ Wait 100ms / 2.0 = 50ms real time
└─ 100ms: Next chunk (scheduled)

Incoming audio:
├─ Real time: 50ms elapsed
├─ arrival_ms = 50ms
└─ But should be 100ms in scenario time!
```

**Impact**: The gap between patient audio and translation audio would appear **shorter** in the tape than it actually is in real-time, because outgoing audio is "compressed" by acceleration but incoming timestamps are not.

### Issue 3: No Adjustment for Service-Provided Timestamps

The code checks if the service sends absolute timestamps (> 1 billion ms) and normalizes them, but doesn't validate if the service's relative timestamps are actually relative to the scenario start.

**Risk**: If the service uses its own timeline (e.g., time since it received the first audio), the timestamps won't align with the scenario timeline.

## Recommendations

### 1. Document Expected Behavior

Add logging to show the gap duration:

```python
# After adding incoming audio to tape
if previous_outgoing_end_ms is not None:
    gap_ms = arrival_ms - previous_outgoing_end_ms
    logger.info(
        f"Gap between outgoing and incoming audio: {gap_ms}ms "
        f"(outgoing ended at {previous_outgoing_end_ms}ms, "
        f"incoming started at {arrival_ms}ms)"
    )
```

### 2. Add Timing Validation

Detect unusually long gaps that might indicate timing issues:

```python
# In ConversationTape or engine
EXPECTED_MAX_LATENCY_MS = 10000  # 10 seconds

if gap_ms > EXPECTED_MAX_LATENCY_MS:
    logger.warning(
        f"Unusually long gap detected: {gap_ms}ms. "
        f"This might indicate timing issues or high service latency."
    )
```

### 3. Verify Service Timestamps

Check what timestamps the service actually sends:

```python
# In engine._listen
logger.debug(
    f"Received translated_audio: "
    f"raw_ts={raw_ts}, arrival_ms={arrival_ms}, "
    f"normalized_ts={timestamp_ms}"
)
```

### 4. Consider Acceleration Adjustment

If using acceleration, consider adjusting incoming timestamps:

```python
# Option: Adjust arrival time by acceleration factor
if self.clock.acceleration != 1.0:
    # Incoming audio should align with accelerated scenario time
    scenario_elapsed_ms = (self.clock.now_ms() - started_at_ms) * self.clock.acceleration
    tape.add_pcm(scenario_elapsed_ms, protocol_event.audio_payload)
else:
    tape.add_pcm(arrival_ms, protocol_event.audio_payload)
```

**Warning**: This would make the tape show "compressed" latency, not real latency. Only use if you want to normalize timeline compression.

## Debugging Long Gaps

### Step 1: Check Raw Timestamps

Add logging in `engine._listen`:

```python
logger.info(
    f"Audio received: type={protocol_event.event_type}, "
    f"raw_ts={protocol_event.timestamp_ms}, "
    f"arrival_ms={arrival_ms}, "
    f"normalized={timestamp_ms}"
)
```

### Step 2: Check Service Latency

Compare when audio was sent vs when translation arrived:

```python
# In conversation_manager
outgoing_ms = turn.first_outbound_ms  # When we sent audio
incoming_ms = turn.first_response_ms  # When translation arrived
latency_ms = incoming_ms - outgoing_ms

logger.info(f"Turn latency: {latency_ms}ms")
```

### Step 3: Inspect call_mix.wav

Listen to the generated `call_mix.wav`:
- Can you hear distinct gaps?
- Do translations sound delayed?
- Is there overlap or cutting off?

### Step 4: Check Service Logs

Verify with the translation service:
- When did it receive the audio?
- When did it start processing?
- When did it send the first translation chunk?
- What timestamps did it include?

## Expected Latency Values

### Good Performance
- First response: 500-1500ms after audio ends
- Streaming starts: 1-2 seconds after audio begins
- Total gap in tape: 1-3 seconds

### Acceptable Performance
- First response: 1500-3000ms
- Total gap: 3-5 seconds

### Poor Performance (Investigate)
- First response: >3000ms
- Total gap: >5 seconds
- Possible causes:
  - Network latency
  - Service overload
  - Processing complexity
  - Timestamp misalignment issue

## Verification Commands

### Extract Timing Information

```bash
# Run test and check logs for gaps
poetry run prod run-test production/tests/scenarios/patient_correction_barge_in.yaml 2>&1 | grep -E "(gap|latency|arrival)"

# Inspect conversation manager output
# Look for first_outbound_ms and first_response_ms per turn
```

### Analyze call_mix.wav

```python
import wave

with wave.open('production_results/patient_correction_barge_in/audio/call_mix.wav', 'rb') as wav:
    duration_s = wav.getnframes() / wav.getframerate()
    print(f"Total duration: {duration_s:.2f} seconds")
```

Compare this with:
- Expected audio durations (14s + 11s = 25s of actual audio)
- Actual call_mix duration (e.g., 30s with 5s of gaps)
- Gap = Total - Audio = 5s of processing delay

## Summary

### Current Behavior is Correct

The ConversationTape **correctly captures real user experience** including:
- ✅ Patient audio at scheduled times
- ✅ Translation audio at actual arrival times
- ✅ Real processing delay as gap/silence
- ✅ Mixed audio file reflects what user hears

### Potential Issues to Check

1. ⚠️ **Service timestamps**: Verify they're relative to scenario start
2. ⚠️ **Acceleration**: Incoming audio doesn't respect acceleration setting
3. ⚠️ **Long delays**: Could be real latency or timestamp misalignment

### Action Items

1. Add debug logging for gaps and timestamps
2. Verify service timestamp format
3. Check if delays are consistent across tests
4. Consider if acceleration should affect incoming timestamps
5. Document expected latency ranges

The "long delay" you're seeing is likely **real service latency**, but worth verifying it's not a timestamp misalignment issue.
