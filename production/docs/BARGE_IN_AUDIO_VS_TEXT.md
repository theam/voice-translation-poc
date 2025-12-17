# Barge-In Metric: Audio vs Text Events

## Critical Distinction

The barge-in metric measures **audio stream timing**, not text timing. This is a crucial distinction because:

### What Users Experience
Users **hear audio**, not text. When a barge-in occurs:
- ❌ **Wrong metric**: Measuring when text deltas stop
- ✅ **Right metric**: Measuring when audio stream stops

### Event Types

The system produces two types of events:

#### 1. Text Events (`translated_delta`)
- Represent incremental text chunks of the translation
- Used by text-based metrics (WER, completeness, etc.)
- **Not suitable** for barge-in evaluation

#### 2. Audio Events (`translated_audio`)
- Represent the actual audio PCM data being played to the user
- Each event contains `audio_payload: bytes`
- **This is what the barge-in metric measures**

## Why This Matters

### Scenario 1: Text Stops, Audio Continues
```
Timeline:
  0ms: Turn 1 starts (patient speaks)
  14000ms: Turn 1 ends
  16000ms: Turn 1 text stops arriving
  18000ms: Turn 1 AUDIO still playing  ← Problem!
  22000ms: Turn 2 starts (barge-in)
  23000ms: Turn 1 audio finally stops
```

**Issue**: If we measured text events, we'd report "excellent" (text stopped at 16s, before barge-in at 22s). But the user heard audio until 23s - 1 second AFTER the barge-in! This is poor barge-in handling.

### Scenario 2: Proper Audio Cutoff
```
Timeline:
  0ms: Turn 1 starts
  14000ms: Turn 1 ends
  16000ms: Turn 1 text stops
  18000ms: Turn 1 audio stops
  22000ms: Turn 2 starts (barge-in)
```

**Result**: No audio after barge-in started. Score: 100 (Excellent)

## Implementation

### Before (Incorrect - Text-based)
```python
late_translations = [
    event for event in previous_turn.inbound_events
    if event.event_type == "translated_delta"  # ❌ Wrong!
    and event.timestamp_ms > barge_in_start_ms
]
```

### After (Correct - Audio-based)
```python
late_audio_events = [
    event for event in previous_turn.inbound_events
    if event.event_type == "translated_audio"  # ✅ Correct!
    and event.timestamp_ms > barge_in_start_ms
]
```

## Verification

The metric now includes debug logging to verify audio events are present:

```python
Event types in conversation: ['translated_audio', 'translated_delta', 'translated_text']
```

If you see:
```
WARNING: No 'translated_audio' events found! Barge-in metric measures audio timing.
```

This means the system is only producing text events, and the metric cannot accurately measure barge-in behavior.

## Audio Event Structure

```python
CollectedEvent(
    event_type="translated_audio",
    timestamp_ms=5234,  # When audio arrived
    audio_payload=b'\x00\x01\x02...',  # PCM audio data
    participant_id="turn1",
    source_language="es",
    target_language="en"
)
```

## How Audio is Captured

From `scenario_engine/engine.py`:
```python
if protocol_event.event_type == "translated_audio" and protocol_event.audio_payload:
    tape.add_pcm(arrival_ms, protocol_event.audio_payload)
```

The system captures audio events and adds them to the "conversation tape" - a complete audio mix of the call.

## Metrics Comparison

| Metric | Measures | Uses Event Type |
|--------|----------|----------------|
| WER | Translation accuracy | `translated_delta` (text) |
| Completeness | Information preservation | `translated_delta` (text) |
| Technical Terms | Terminology accuracy | `translated_delta` (text) |
| **Barge-In** | **Audio cutoff timing** | **`translated_audio` (audio)** |

## Testing Considerations

### Verify Audio Events Exist

Before running barge-in tests, confirm your translation service produces audio events:

```bash
# Run test and check logs
poetry run prod run-test production/tests/scenarios/patient_correction_barge_in.yaml

# Look for this line in logs:
"Event types in conversation: ['translated_audio', ...]"
```

### If No Audio Events

If only text events exist, you have options:

1. **Update translation service** to produce audio events
2. **Use text as proxy** (less accurate, but can measure text timing)
3. **Disable barge-in metric** for this service

### Adjusting the Metric

If you must use text events as a proxy (not recommended):

```python
# In barge_in.py, change:
event.event_type == "translated_audio"
# To:
event.event_type == "translated_delta"
```

But note: This measures when text stops, not when audio stops. The score will not accurately reflect user experience.

## Key Takeaways

1. ✅ **Barge-in metric uses `translated_audio` events**
2. ✅ **Audio timing ≠ Text timing** (audio typically lags text)
3. ✅ **User experience = What they hear, not what they read**
4. ✅ **Metric warns if no audio events found**
5. ✅ **Verify your system produces audio events before testing**

## Related Files

- **Metric Implementation**: `production/metrics/barge_in.py`
- **Audio Sink**: `production/capture/audio_sink.py`
- **Audio Events**: `production/acs_emulator/message_handlers/legacy_audio.py`
- **Protocol Events**: `production/acs_emulator/protocol_adapter.py`

## Example Log Output

```
INFO: Found barge-in pair: patient_initial_statement -> patient_correction (barge-in at 22000ms)
INFO: Event types in conversation: ['translated_audio', 'translated_delta']
DEBUG: No late audio from patient_initial_statement after barge-in at 22000ms
INFO: Barge-in evaluation: patient_correction - Score: 95.2, Cutoff: 0ms, Mixing: False, Response: 1200ms
```

Perfect barge-in handling: Audio stopped before the interruption even occurred!
