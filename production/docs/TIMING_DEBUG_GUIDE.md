# Timing Debug Guide

## Overview

Comprehensive logging has been added to track audio timing throughout the system. This guide explains what each log message means and how to interpret the results.

## Log Messages

### 🎤 Outgoing Audio (Patient Speaking)

**START:**
```
🎤 OUTGOING AUDIO START: turn='patient_initial_statement', scenario_time=0ms, wall_clock=1234567ms
```
- `turn`: Which turn is speaking
- `scenario_time`: When this should play according to the scenario (0ms for first turn)
- `wall_clock`: Actual system time when sent

**END:**
```
🎤 OUTGOING AUDIO END: turn='patient_initial_statement', scenario_time=14000ms, wall_clock=1234581ms, total_chunks=140, duration=14000ms
```
- `scenario_time`: When audio finished in scenario timeline
- `total_chunks`: Number of audio frames sent
- `duration`: Total audio duration in ms

### 🔊 Incoming Audio (Translated Audio)

**START:**
```
🔊 INCOMING AUDIO START: turn='patient_initial_statement', arrival_ms=16234ms, wall_clock=1250801ms, raw_ts=None, ts_source=arrival_time, payload_size=3200 bytes
```
- `turn`: Which turn this translation belongs to
- `arrival_ms`: Time since scenario started (relative timeline)
- `wall_clock`: Actual system time when received
- `raw_ts`: Timestamp from the service (None if not provided)
- `ts_source`: Where timestamp came from:
  - `arrival_time`: Using actual arrival time (most common)
  - `service_relative`: Service provided relative timestamp
  - `absolute_normalized`: Service sent absolute timestamp, we normalized it
- `payload_size`: Size of audio chunk in bytes

### ⏱️ Turn Summary (After Scenario Completes)

**Per Turn:**
```
Turn 'patient_initial_statement' (0ms): Good morning doctor. I'm here because...
  ⏱️  VAD-aware latency: 2000ms (last_outbound=14000ms → first_response=16000ms)
  ⏱️  Total latency: 16000ms (includes 14000ms speaking + 2000ms processing)
  🔊 Audio: 145 events, first=2234ms, last=16234ms, duration=14000ms
  📝 Text: 23 events, first=500ms, last=15800ms
```

- **VAD-aware latency**: Pure processing time (from last audio chunk to first translation)
  - This is the TRUE service latency with VAD enabled
  - Use this for performance monitoring
- **Total latency**: Speaking + processing time (from first to first)
  - Includes the time the user was speaking
  - Useful for end-to-end UX measurement
- **Audio events**: Count and timing of translation audio chunks
- **Text events**: Count and timing of text deltas (for comparison)

**IMPORTANT**: With VAD (Voice Activity Detection) enabled, the service waits for the speaker to stop before processing. Therefore, **VAD-aware latency** is the correct metric for measuring translation service performance.

**Gap Between Turns:**
```
  ⏸️  Gap from previous turn: 2000ms (prev ended at 16234ms, current started at 18234ms)
```

- **Gap**: Silence between turns
- Shows processing delay between turns

**Warning for Long Gaps:**
```
  ⚠️  Long gap detected: 8000ms - This may indicate high service latency or timing issues
```

### 🎵 Conversation Tape (When Writing call_mix.wav)

```
🎵 CONVERSATION TAPE: total_segments=285, timeline_span=0ms-30234ms, duration=30234ms
🎵 MIXED WAV: total_samples=483744, duration=30.23s, sample_rate=16000Hz
```

- `total_segments`: Number of audio chunks mixed
- `timeline_span`: Range of timestamps in the tape
- `duration`: Total duration of the mixed audio

## Example Output Analysis

### Good Performance (VAD-aware)

```
🎤 OUTGOING AUDIO START: turn='patient_initial_statement', scenario_time=0ms, wall_clock=1000000ms
🎤 OUTGOING AUDIO END: turn='patient_initial_statement', scenario_time=14000ms, wall_clock=1014000ms
🔊 INCOMING AUDIO START: turn='patient_initial_statement', arrival_ms=15500ms, wall_clock=1015500ms, ts_source=arrival_time

Turn 'patient_initial_statement':
  ⏱️  VAD-aware latency: 1500ms (last_outbound=14000ms → first_response=15500ms)
  ⏱️  Total latency: 15500ms (includes 14000ms speaking + 1500ms processing)
```

**Analysis**:
- Patient audio: 0-14000ms (14 seconds speaking)
- Translation arrives: 15500ms
- **VAD-aware latency: 1500ms (1.5 seconds)** ✅ Good processing time!
- Total time including speaking: 15500ms

### Problem: Long Delay

```
🎤 OUTGOING AUDIO START: turn='patient_initial_statement', scenario_time=0ms, wall_clock=1000000ms
🎤 OUTGOING AUDIO END: turn='patient_initial_statement', scenario_time=14000ms, wall_clock=1014000ms
🔊 INCOMING AUDIO START: turn='patient_initial_statement', arrival_ms=22000ms, wall_clock=1022000ms, ts_source=arrival_time

Turn 'patient_initial_statement':
  ⏱️  VAD-aware latency: 8000ms (last_outbound=14000ms → first_response=22000ms)
  ⏱️  Total latency: 22000ms (includes 14000ms speaking + 8000ms processing)
  ⚠️  Long gap detected: 8000ms
```

**Analysis**:
- Patient audio: 0-14000ms (14 seconds speaking)
- Translation arrives: 22000ms
- **VAD-aware latency: 8000ms (8 seconds)** ⚠️ High processing time!

**Possible causes**:
1. Service is actually slow (real latency)
2. Network delay
3. Service overloaded
4. Processing complex audio

### Problem: Timestamp Mismatch

```
🎤 OUTGOING AUDIO START: turn='patient_initial_statement', scenario_time=0ms, wall_clock=1000000ms
🎤 OUTGOING AUDIO END: turn='patient_initial_statement', scenario_time=14000ms, wall_clock=1014000ms
🔊 INCOMING AUDIO START: turn='patient_initial_statement', arrival_ms=15500ms, wall_clock=1015500ms, raw_ts=5000, ts_source=service_relative
```

**Analysis**:
- Service sent `raw_ts=5000`
- But we're using `arrival_ms=15500ms`
- **Mismatch!** Service timeline doesn't match scenario timeline

**Action**: Check if service timestamps are relative to:
- Scenario start ✅ (should be 14000+)
- Service start ❌ (would be ~1000-2000)
- First audio received ❌ (would be ~0)

## Debugging Steps

### Step 1: Check Basic Timing

Run a test and look for the emoji markers:

```bash
docker compose exec vt-app bash -c "cd /app && poetry run prod run-test production/tests/scenarios/patient_correction_barge_in.yaml" 2>&1 | grep -E "🎤|🔊|⏱️|⏸️|🎵"
```

### Step 2: Calculate Gaps

```bash
# Extract timing data
docker compose exec vt-app bash -c "cd /app && poetry run prod run-test production/tests/scenarios/patient_correction_barge_in.yaml" 2>&1 | grep -E "OUTGOING AUDIO END|INCOMING AUDIO START"
```

Compare the times:
- Outgoing END scenario_time: e.g., 14000ms
- Incoming START arrival_ms: e.g., 16500ms
- **Gap = 16500 - 14000 = 2500ms**

### Step 3: Check Timestamp Source

Look for `ts_source` in incoming audio logs:

- `arrival_time`: ✅ Using wall-clock (most reliable)
- `service_relative`: ⚠️ Service provided timestamp (verify it's correct)
- `absolute_normalized`: ⚠️ Service sent absolute timestamp (should be normalized correctly)

### Step 4: Verify Service Behavior

If `ts_source=service_relative` and gaps seem wrong:

1. Check service logs to see what timestamps it sends
2. Verify service timestamp is relative to scenario start
3. If not, consider using `arrival_time` instead

### Step 5: Listen to call_mix.wav

The ultimate test:

```bash
# After running test
open production_results/patient_correction_barge_in/audio/call_mix.wav
```

Listen for:
- Gaps between patient and translation
- Whether timing feels natural
- If audio cuts off or overlaps

## What to Expect

### Turn 1 (patient_initial_statement)
```
🎤 OUTGOING: scenario_time=0-14000ms
🔊 INCOMING: arrival_ms=~15000-29000ms (depending on service speed)
Gap: ~1000-3000ms (normal processing delay)
```

### Turn 2 (patient_correction, barge-in at 22000ms)
```
🎤 OUTGOING: scenario_time=22000-33000ms
🔊 INCOMING: arrival_ms=~35000-46000ms
Gap from Turn 1: ~6000-8000ms (depends on when Turn 1 ended)
```

### Full Conversation
```
🎵 CONVERSATION TAPE: duration=~45000-50000ms (45-50 seconds total)
```

Components:
- Turn 1 audio: 14s
- Turn 1 translation: 14s
- Gap/processing: 2-3s
- Turn 2 audio: 11s
- Turn 2 translation: 11s
- Total: ~52-55s

## Common Issues and Solutions

### Issue 1: Very Long Gaps (>10s)

**Symptoms:**
```
⚠️  Long gap detected: 12000ms
```

**Possible Causes:**
1. Service is genuinely slow
2. Timestamp misalignment
3. Clock acceleration issue

**Debug:**
```bash
# Check if raw_ts is provided and what value
grep "raw_ts=" logs.txt

# If raw_ts is small (e.g., 1000-5000):
# → Service timeline doesn't match scenario timeline
# → Using arrival_time instead is correct
```

### Issue 2: Negative Gaps or Audio Arriving Before Sent

**Symptoms:**
```
🔊 INCOMING AUDIO START: arrival_ms=500ms
🎤 OUTGOING AUDIO END: scenario_time=14000ms
```
Translation arrives before patient finished speaking!

**Cause:** Timestamp coordination issue

**Solution:** Verify service isn't sending its own timeline

### Issue 3: Gaps Increase Over Time

**Symptoms:**
- Turn 1 gap: 2000ms
- Turn 2 gap: 4000ms
- Turn 3 gap: 6000ms

**Cause:** Clock drift or accumulating latency

**Debug:** Check if wall_clock times are drifting from scenario_time

### Issue 4: Acceleration Artifacts

**Symptoms:**
```
acceleration=2.0
🎤 OUTGOING END: wall_clock elapsed=7000ms (14s audio in 7s real time)
🔊 INCOMING START: arrival_ms=7500ms
Gap appears to be: 7500 - 14000 = -6500ms (negative!)
```

**Cause:** Outgoing uses accelerated time, incoming uses wall-clock

**Solution:** This is expected. The tape timeline uses scenario time (14000ms), not wall-clock time.

## Summary

The logging helps you:

1. **Verify timing sources**: Are timestamps coming from arrival or service?
2. **Measure real latency**: How long does processing actually take?
3. **Detect misalignment**: Are service timestamps coordinated with scenario?
4. **Identify issues**: Long gaps, negative gaps, drift
5. **Validate tape**: Does call_mix.wav match expectations?

Look for the emoji markers in logs to quickly spot timing events! 🎤🔊⏱️⏸️🎵
