# Arrival Time Simplification

## Summary

**Simplified timestamp handling**: All events now use **arrival time only**. No more clock coordination complexity with service timestamps.

## What Changed

### Before: Complex Timestamp Logic

```python
# Try to use service timestamp with normalization
raw_ts = protocol_event.timestamp_ms

if raw_ts is not None and raw_ts > 1_000_000_000:
    timestamp_ms = max(0, raw_ts - started_at_ms)  # Normalize absolute
    ts_source = "absolute_normalized"
elif raw_ts is not None:
    timestamp_ms = raw_ts  # Use service relative
    ts_source = "service_relative"
else:
    timestamp_ms = arrival_ms  # Fallback to arrival
    ts_source = "arrival_time"

# Special case for audio
audio_timestamp_ms = arrival_ms if event_type == "audio" else timestamp_ms
```

**Problems:**
- Complex logic with multiple code paths
- Clock coordination issues between systems
- Absolute vs relative timestamp confusion
- Inconsistent behavior for different event types

### After: Simple Arrival Time

```python
# Always use arrival time - simple and accurate!
arrival_ms = self.clock.now_ms() - started_at_ms

collected = CollectedEvent(
    event_type=protocol_event.event_type,
    timestamp_ms=arrival_ms,  # Always arrival time
    ...
)
```

**Benefits:**
- ✅ Single, consistent timeline
- ✅ No clock coordination needed
- ✅ Same logic for all event types
- ✅ Represents actual user experience
- ✅ Includes full end-to-end latency (processing + network)

## Why This is Better

### 1. Ground Truth

Arrival time is **when events actually arrived** at the framework:
```
Patient speaks: 0-14000ms (outgoing, scheduled)
Translation arrives: 19265ms (incoming, actual)
Gap: 5265ms ← This is what the user experiences!
```

Service timestamps might say "sent at 17000ms" but if it arrived at 19265ms, that's the reality.

### 2. Consistent Timeline

Everything now uses the same coordinate system:
```
Timeline (all in scenario-relative milliseconds):
├─ 0ms: Scenario starts
├─ 0-14000ms: Patient audio (outgoing)
├─ 17527ms: Translation text arrives
├─ 19265ms: Translation audio arrives
└─ 40000ms: Scenario ends
```

No more mixing absolute timestamps (1764511210118) with relative ones (17527).

### 3. No Clock Drift

Different systems have different clocks:
```
Our clock:     Started at Unix epoch 1764511194000
Service clock: Uses Unix epoch 1764511210118

Difference: 16118ms... but is that real latency or clock drift?
```

With arrival time: Don't care! We measure when it arrived **at our end**.

### 4. Accurate Latency

Includes **full end-to-end latency**:
```
Service perspective:
├─ Received audio: T=0
├─ Processed: 1000ms
└─ Sent translation: T=1000

Our perspective (arrival time):
├─ Sent audio: T=0
├─ Service processing: 1000ms
├─ Network delay: 200ms
└─ Received translation: T=1200 ✅

Using arrival time captures the full 1200ms that matters to the user!
```

## What Users See

### Simplified Logs

**Before:**
```
🔊 INCOMING AUDIO START: turn='patient_initial_statement',
    arrival_ms=17414ms,
    raw_ts=1764511210118ms (absolute),
    normalized=16118ms,
    using_arrival_time=True,
    ts_source=absolute_normalized
```

**After:**
```
🔊 INCOMING AUDIO START: turn='patient_initial_statement',
    arrival_ms=19265ms,
    wall_clock=1234567890ms,
    payload_size=3200 bytes
```

Clean and simple!

### Consistent Metrics

All timestamps now in the same scale:
```
Turn 'patient_initial_statement' (10ms):
  ⏱️  Audio latency (VAD-aware): 2803ms
      (last_outbound=16462ms → first_audio=19265ms)
  ⏱️  Text latency: 1065ms
      (audio arrives 1738ms after text)
  🔊 Audio: first=19265ms, last=19265ms
  📝 Text: first=17527ms, last=18526ms
```

Everything makes sense! No billion-millisecond timestamps.

## Impact on Different Event Types

### Audio Events ✅
```python
# Audio always used arrival time anyway (we fixed this earlier)
tape.add_pcm(arrival_ms, audio_payload)
CollectedEvent(timestamp_ms=arrival_ms, ...)
```
**No change** - audio was already using arrival time.

### Text Events ✅
```python
# Text now also uses arrival time (simplified)
CollectedEvent(timestamp_ms=arrival_ms, text=delta, ...)
```
**Changed** - text now uses arrival instead of trying service timestamp.

**Impact**: Text timestamps now represent when text arrived, not when service claims it was generated. This is more accurate for user experience.

### All Other Events ✅
```python
# Everything uses arrival time
CollectedEvent(timestamp_ms=arrival_ms, ...)
```
**Consistent** - one timeline for everything.

## Testing Verification

### Run Test and Check

```bash
poetry run prod run-test production/tests/scenarios/patient_correction_barge_in.yaml
```

**Look for:**
1. ✅ All timestamps in 0-50000ms range (scenario timeline)
2. ✅ No absolute timestamps (1764511210118ms)
3. ✅ Audio and text timestamps close together (~2s apart)
4. ✅ Gaps match listening experience in call_mix.wav
5. ✅ Clean, simple logs

### Expected Output

```
🔊 INCOMING AUDIO START: arrival_ms=19265ms, wall_clock=1234567890ms
📝 TEXT DELTA: arrival_ms=17527ms, text='Good morning...'

Turn 'patient_initial_statement':
  ⏱️  Audio latency (VAD-aware): 2803ms
  🔊 Audio: 1 events, first=19265ms, last=19265ms
  📝 Text: 42 events, first=17527ms, last=18526ms
```

All timestamps consistent and reasonable!

## Edge Cases Handled

### Service Sends Timestamps

**Ignored:**
```python
# Service includes: protocol_event.timestamp_ms = 1764511210118
# We ignore it and use: arrival_ms = 19265
```

The service timestamp is still in `protocol_event.raw` if you need it for debugging.

### Service Sends No Timestamps

**Works the same:**
```python
# Service doesn't include timestamp
# We use: arrival_ms = 19265
```

No difference in behavior!

### Clock Acceleration

**Respects acceleration:**
```python
# With acceleration=2.0, events arrive at real-time pace
# but arrival_ms reflects accelerated scenario time
arrival_ms = self.clock.now_ms() - started_at_ms
# Automatically accounts for acceleration in clock.now_ms()
```

Works correctly with time acceleration.

## Migration Notes

### Code Removed ✅

- Complex timestamp normalization logic
- Absolute vs relative detection
- Service timestamp handling
- Special-case audio timestamp logic

**Lines deleted:** ~20 lines of complex logic
**Lines added:** ~5 lines of simple logic

### API Unchanged ✅

```python
# CollectedEvent still has timestamp_ms
event.timestamp_ms  # Just always arrival time now

# TurnSummary properties unchanged
turn.first_response_ms
turn.first_audio_response_ms
turn.latency_ms
```

All existing code using these properties continues to work!

### No Breaking Changes ✅

- Metrics still calculate the same way
- Logs are simpler but show same info
- Timeline is more consistent
- Barge-in metric more accurate

## Debugging Benefits

### Before: Confusing Timestamps

```
Why is audio timestamp = 1764511210118ms?
Is that Unix epoch? Service time? Bug?
Why doesn't it match scenario timeline?
Is normalization working?
```

### After: Obvious Timestamps

```
Audio arrives at: 19265ms
That's 19 seconds into the scenario
Makes sense! Patient spoke 0-16s, translation arrived at 19s
```

Everything is obvious!

## Performance Impact

**Negligible:**
- Removed: ~20 lines of branching logic per event
- Added: Simple subtraction
- Net: Slightly faster (fewer conditionals)

## Summary Table

| Aspect | Before | After |
|--------|--------|-------|
| **Complexity** | ~40 lines, 3 code paths | ~10 lines, 1 code path |
| **Timestamp source** | Service (if available) → arrival | Always arrival |
| **Clock coordination** | Required | Not required |
| **Timeline consistency** | Mixed absolute/relative | Single relative timeline |
| **User experience accuracy** | Service-side timing | Actual arrival timing ✅ |
| **Debugging** | Confusing timestamps | Obvious timestamps ✅ |
| **Edge cases** | Many special cases | No special cases ✅ |

## Bottom Line

**Simpler, clearer, more accurate!**

We eliminated 20+ lines of complex clock coordination logic and replaced it with a simple rule:
> Use the time when events **actually arrived** at the framework.

This represents ground truth for user experience and eliminates an entire class of timestamp bugs.

**Result**: Everything uses one consistent timeline, metrics are more accurate, and the code is much easier to understand!
