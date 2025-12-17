# VAD-Aware Latency Calculation

## Overview

With Voice Activity Detection (VAD) enabled, the translation service waits for the speaker to **finish talking** before starting translation. This means latency should be measured from the **last audio chunk** sent, not the first.

## Why This Matters

### Without VAD-Aware Calculation (Wrong)

```
Timeline:
├─ 0ms: First audio chunk sent
├─ 100ms: Audio chunk
├─ 200ms: Audio chunk
├─ ...
├─ 14000ms: Last audio chunk sent
├─ 16000ms: First translation received

Incorrect latency: 16000 - 0 = 16000ms ❌
(Includes 14 seconds of speaking time!)
```

### With VAD-Aware Calculation (Correct)

```
Timeline:
├─ 0ms: First audio chunk sent
├─ 100ms: Audio chunk
├─ 200ms: Audio chunk
├─ ...
├─ 14000ms: Last audio chunk sent ← VAD detects end of speech
├─ 16000ms: First translation received

Correct latency: 16000 - 14000 = 2000ms ✅
(Only processing time!)
```

## Implementation

### TurnSummary Properties

**1. `latency_ms` (Primary - VAD-aware)**
```python
@property
def latency_ms(self) -> Optional[int]:
    """Latency from last outbound audio to first response.

    This is the TRUE processing latency with VAD enabled.
    """
    return self.first_response_ms - self.last_outbound_ms
```

**Use this for:**
- Measuring actual translation service performance
- Comparing different service configurations
- SLA monitoring
- Performance optimization

**2. `first_chunk_latency_ms` (Total time)**
```python
@property
def first_chunk_latency_ms(self) -> Optional[int]:
    """Latency from FIRST outbound audio to first response.

    Total time = speaking time + processing time.
    """
    return self.first_response_ms - self.first_outbound_ms
```

**Use this for:**
- Understanding total user experience duration
- Calculating end-to-end time
- Comparing with non-VAD systems

### Fields Tracked

```python
@dataclass
class TurnSummary:
    first_outbound_ms: Optional[int]  # When first audio sent
    last_outbound_ms: Optional[int]   # When last audio sent (NEW!)
    first_response_ms: Optional[int]  # When first translation received
```

## Log Output

### New Format

```
Turn 'patient_initial_statement' (0ms): Good morning doctor...
  ⏱️  VAD-aware latency: 2000ms (last_outbound=14000ms → first_response=16000ms)
  ⏱️  Total latency: 16000ms (includes 14000ms speaking + 2000ms processing)
```

**Breakdown:**
- **VAD-aware latency (2000ms)**: Pure processing time
- **Total latency (16000ms)**: Speaking + processing
- **Audio duration (14000ms)**: How long the speaker talked

### Interpretation

#### Good Performance
```
⏱️  VAD-aware latency: 1500ms
⏱️  Total latency: 15500ms (includes 14000ms speaking + 1500ms processing)
```
Translation starts **1.5 seconds** after speaker stops. ✅

#### Poor Performance
```
⏱️  VAD-aware latency: 8000ms
⏱️  Total latency: 22000ms (includes 14000ms speaking + 8000ms processing)
```
Translation starts **8 seconds** after speaker stops. ⚠️ Investigate!

## Timeline Diagrams

### Example 1: Good VAD-aware Latency

```
Patient Speaking:
├─────────────────────────────────────────────────┤ (14 seconds)
0ms                                            14000ms

VAD Processing:
                                                  ├─────┤ (2 seconds)
                                               14000ms  16000ms

Translation Audio:
                                                        ├──────────────┤
                                                     16000ms       30000ms

Metrics:
- Audio duration: 14000ms
- VAD-aware latency: 2000ms (16000 - 14000)
- Total latency: 16000ms (16000 - 0)
```

### Example 2: High VAD-aware Latency

```
Patient Speaking:
├─────────────────────────────────────────────────┤ (14 seconds)
0ms                                            14000ms

VAD Processing:
                                                  ├────────────────┤ (8 seconds!)
                                               14000ms          22000ms

Translation Audio:
                                                                      ├──────────────┤
                                                                   22000ms       36000ms

Metrics:
- Audio duration: 14000ms
- VAD-aware latency: 8000ms (22000 - 14000) ⚠️ High!
- Total latency: 22000ms (22000 - 0)
```

## Use Cases

### Use Case 1: Performance Monitoring

Monitor VAD-aware latency for service health:

```python
for turn in turns:
    if turn.latency_ms > 3000:  # Alert if processing takes >3s
        logger.warning(f"High latency: {turn.latency_ms}ms for turn {turn.turn_id}")
```

### Use Case 2: Service Comparison

Compare different translation services:

```python
service_a_latency = 1500ms  # VAD-aware
service_b_latency = 4000ms  # VAD-aware

# Service A is 2.5x faster at processing
```

### Use Case 3: End-to-End UX

Calculate total user waiting time:

```python
total_time = turn.first_chunk_latency_ms
# User starts speaking → hears translation
# Useful for UX studies
```

### Use Case 4: Barge-In Metric

The barge-in metric should use actual arrival times (already does):

```python
# Correctly measures when audio actually stopped playing
cutoff_latency = last_audio_event_ms - barge_in_start_ms
```

## Migration Notes

### Old Code (Before)
```python
# Only had first_outbound_ms
latency = turn.first_response_ms - turn.first_outbound_ms
# This included speaking time!
```

### New Code (After)
```python
# Now has both first and last outbound
latency = turn.latency_ms  # VAD-aware (uses last_outbound)
total = turn.first_chunk_latency_ms  # Total time (uses first_outbound)
```

### Backward Compatibility

The `latency_ms` property now returns VAD-aware latency. If `last_outbound_ms` is not available (shouldn't happen), it falls back to `first_outbound_ms`:

```python
outbound_ref = self.last_outbound_ms if self.last_outbound_ms is not None else self.first_outbound_ms
```

## Expected Values

### VAD-Aware Latency (Pure Processing)

**Excellent**: <1000ms
- Service starts translating almost immediately
- Highly responsive

**Good**: 1000-2000ms
- Acceptable performance
- Typical for real-time services

**Acceptable**: 2000-3000ms
- Noticeable delay
- May feel slightly sluggish

**Poor**: 3000-5000ms
- Significant delay
- User experience degraded

**Very Poor**: >5000ms
- Unacceptable for real-time translation
- Investigate service issues

### Total Latency (Speaking + Processing)

Depends on audio duration:
- Short phrase (2s): 2000 + 1500 = 3500ms
- Medium (7s): 7000 + 1500 = 8500ms
- Long (14s): 14000 + 1500 = 15500ms

**Key insight**: Total latency grows with audio length, but VAD-aware latency should stay constant!

## Debugging

### Check if VAD is Working

If VAD-aware latency is similar to total latency:

```
⏱️  VAD-aware latency: 15000ms
⏱️  Total latency: 15500ms (includes 500ms speaking + 15000ms processing)
```

**Problem**: Service may not be using VAD, or VAD is not detecting end of speech correctly.

**Expected with VAD**:
```
⏱️  VAD-aware latency: 1500ms
⏱️  Total latency: 15500ms (includes 14000ms speaking + 1500ms processing)
```

### Verify Last Outbound Tracking

Check that `last_outbound_ms` is being set:

```python
logger.info(f"First outbound: {turn.first_outbound_ms}ms")
logger.info(f"Last outbound: {turn.last_outbound_ms}ms")
logger.info(f"Audio duration: {turn.last_outbound_ms - turn.first_outbound_ms}ms")
```

Should see a duration matching the audio file length.

## Summary

| Metric | Formula | What It Measures | When to Use |
|--------|---------|------------------|-------------|
| **VAD-aware latency** | `last_outbound → first_response` | Pure processing time | Service performance, SLAs |
| **Total latency** | `first_outbound → first_response` | Speaking + processing | End-to-end UX, total time |
| **Audio duration** | `last_outbound - first_outbound` | How long user spoke | Context for latency |

**Key takeaway**: With VAD enabled, always use **VAD-aware latency** to measure service performance. Total latency is misleading because it includes speaking time.
