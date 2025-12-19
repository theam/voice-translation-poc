# Outbound Timestamp Fix - Scenario Time vs Wall-Clock Time

## The Problem

**Symptom**: Latency calculations didn't match the actual gap heard in `call_mix.wav`

```
In call_mix.wav: Audio ends at ~13 seconds
In logs: last_outbound=16394ms (16.4 seconds)
Difference: 3.4 seconds!

Calculated latency: 2686ms
Actual gap in audio: ~5200ms
Off by: ~2.5 seconds!
```

## Root Cause

Outbound audio timestamps were being recorded differently in two places:

### ConversationTape (Correct) ✅
```python
# audio.py
send_at = turn.start_at_ms + offset_ms  # Scenario timeline
self.tape.add_pcm(send_at, data)  # 6ms, 106ms, ..., 13806ms
```

### ConversationManager (Wrong) ❌
```python
# conversation_manager.py
def register_outgoing(turn_id, message):
    timestamp_ms = self.now_relative_ms()  # Wall-clock time!
    turn.record_outgoing(message, timestamp_ms)
```

**The mismatch:**
- **Tape**: Used `send_at` (scenario timeline)
- **ConversationManager**: Used wall-clock time (includes all sleep delays)

## Timeline Breakdown

### Scenario Timeline (What Should Be Used)
```
Turn starts: 6ms
├─ Chunk 1: send_at = 6ms + 0 = 6ms
├─ Chunk 2: send_at = 6ms + 100 = 106ms
├─ Chunk 3: send_at = 6ms + 200 = 206ms
├─ ...
└─ Chunk 138: send_at = 6ms + 13800 = 13806ms ← Last chunk

first_outbound_ms: 6ms
last_outbound_ms: 13806ms ← Correct!
Audio duration: 13.8 seconds
```

### Wall-Clock Timeline (What Was Being Used)
```
Turn starts: 6ms (wall-clock)
├─ Chunk 1: sent at 6ms (wall-clock)
├─ Sleep 100ms
├─ Chunk 2: sent at 106ms + δ (wall-clock)
├─ Sleep 100ms
├─ Chunk 3: sent at 206ms + δ (wall-clock)
├─ ...
└─ Chunk 138: sent at ~16394ms (wall-clock) ← Wrong!

first_outbound_ms: 6ms
last_outbound_ms: 16394ms ← Too late!
Difference: 16394 - 13806 = 2588ms of accumulated delays
```

The 2.6 second difference is the accumulated sleep time and processing overhead.

## Impact on Latency Calculation

### With Wrong Timestamps
```python
last_outbound = 16394ms  # Wall-clock (wrong)
first_audio = 19080ms    # Arrival time (correct)
latency = 19080 - 16394 = 2686ms ❌ Too short!
```

### With Correct Timestamps
```python
last_outbound = 13806ms  # Scenario time (correct)
first_audio = 19080ms    # Arrival time (correct)
latency = 19080 - 13806 = 5274ms ✅ Matches audio!
```

## The Fix

### 1. Make timestamp_ms Optional in register_outgoing
```python
def register_outgoing(
    self,
    turn_id: str,
    message: dict,
    *,
    participant_id: Optional[str] = None,
    timestamp_ms: Optional[int] = None,  # NEW: Optional explicit timestamp
) -> None:
    # Use provided timestamp (scenario timeline) or fall back to wall-clock
    if timestamp_ms is None:
        timestamp_ms = self.now_relative_ms()

    turn.record_outgoing(message, timestamp_ms=timestamp_ms, ...)
```

### 2. Pass send_at from Audio Processor
```python
# audio.py
self.conversation_manager.register_outgoing(
    turn.id,
    payload,
    participant_id=turn.id,
    timestamp_ms=send_at,  # Use scenario timeline!
)
```

## Why This is Correct

### Consistency with Tape
Both now use the same timeline:
```python
# Tape
self.tape.add_pcm(send_at, data)  # 13806ms

# ConversationManager
register_outgoing(..., timestamp_ms=send_at)  # 13806ms

# Both use scenario time! ✅
```

### Represents Playback Time
`send_at` represents **when the audio chunk plays** in the scenario timeline:
```
0ms: Scenario starts
6ms: Turn starts, first chunk plays
106ms: Second chunk plays
...
13806ms: Last chunk plays ← This is when audio ends!
19080ms: Translation arrives

Gap = 19080 - 13806 = 5274ms ← What user hears!
```

### Independent of Processing Speed
```
Fast machine:
- Chunks sent quickly
- Wall-clock: 14000ms
- Scenario time: 13806ms ← Same!

Slow machine:
- Chunks sent slowly
- Wall-clock: 17000ms
- Scenario time: 13806ms ← Still same!
```

Scenario time is **independent of system performance**, which is correct for measuring service latency.

## What Changed

### Before Fix
```
Turn 'patient_initial_statement':
  ⏱️  Audio latency (VAD-aware): 2686ms
      (last_outbound=16394ms → first_audio=19080ms)

In call_mix.wav: ~5 second gap
In logs: 2.6 second latency
Mismatch: ~2.4 seconds ❌
```

### After Fix
```
Turn 'patient_initial_statement':
  ⏱️  Audio latency (VAD-aware): 5274ms
      (last_outbound=13806ms → first_audio=19080ms)

In call_mix.wav: ~5 second gap
In logs: 5.3 second latency
Matches! ✅
```

## Backward Compatibility

### Other Callers Still Work ✅
```python
# hangup.py - no timestamp passed, uses wall-clock (fine for control messages)
register_outgoing(turn.id, payload)

# loopback_text.py - no timestamp passed, uses wall-clock (fine for text)
register_outgoing(turn.id, payload)

# Both use default (wall-clock) since timestamp_ms not provided
```

### Only Audio Changed
```python
# audio.py - now passes explicit timestamp
register_outgoing(turn.id, payload, timestamp_ms=send_at)
```

Only audio processing was updated to use scenario time. Everything else continues to work as before.

## Verification

Run a test and compare:

### Check Logs
```
Turn 'patient_initial_statement':
  ⏱️  Audio latency (VAD-aware): 5274ms
      (last_outbound=13806ms → first_audio=19080ms)
```

### Listen to call_mix.wav
```
0-13.8s: Patient audio
13.8-19.1s: Gap (5.3 seconds)
19.1s+: Translation audio
```

**They should match now!** The logged latency matches the gap you hear.

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Tape timeline** | Scenario time (send_at) | Scenario time (send_at) ✅ |
| **ConversationManager timeline** | Wall-clock time | Scenario time (send_at) ✅ |
| **last_outbound_ms** | 16394ms (wrong) | 13806ms (correct) ✅ |
| **Calculated latency** | 2686ms | 5274ms ✅ |
| **Actual gap in audio** | ~5200ms | ~5200ms |
| **Match?** | ❌ Off by 2.5s | ✅ Matches! |

**Bottom line**: Outbound timestamps now use scenario time (when audio plays) instead of wall-clock time (when chunks are sent). This makes latency calculations match the actual audio experience!
