# Participant Audio Broadcast Implementation Plan

## Overview

Enable participants in a call to hear each other's original (untranslated) audio in addition to translated responses from the upstream service.

---

## Current Flow

```
┌─────────────┐
│ Participant │
│   (Alice)   │
└──────┬──────┘
       │ 1. Send audio
       ▼
┌─────────────┐
│   Backend   │
└──────┬──────┘
       │ 2. Forward to upstream
       ▼
┌─────────────┐
│  Upstream   │
│ Translation │
│   Service   │
└──────┬──────┘
       │ 3. Translated audio
       ▼
┌─────────────┐
│   Backend   │
└──────┬──────┘
       │ 4. Broadcast to ALL
       ▼
┌─────────────┬─────────────┐
│ Alice       │ Bob         │
│ (hears own  │ (hears      │
│ translation)│ translation)│
└─────────────┴─────────────┘
```

**Problem**: Participants only hear translations, not each other's original voice.

---

## Desired Flow

```
┌─────────────┐
│ Participant │
│   (Alice)   │
└──────┬──────┘
       │ 1. Send audio
       ▼
┌─────────────┐
│   Backend   │◄────────────┐
└──────┬──────┘             │
       │ 2a. Forward        │ 2b. Broadcast
       │     to upstream    │     to others
       ▼                    │     (not Alice)
┌─────────────┐             │
│  Upstream   │             │
│ Translation │             │
│   Service   │             │
└──────┬──────┘             │
       │ 3. Translated      │
       │    audio           │
       ▼                    │
┌─────────────┐             │
│   Backend   │             │
└──────┬──────┘             │
       │ 4. Broadcast       │
       │    to ALL          │
       ▼                    ▼
┌─────────────┬─────────────┐
│ Alice       │ Bob         │
│ (hears own  │ (hears      │
│ translation)│ translation │
│             │ + Alice's   │
│             │ original    │
│             │ audio)      │
└─────────────┴─────────────┘
```

**Result**: Bob hears Alice's original voice AND her translated audio.

---

## Implementation Details

### 1. Backend Changes

#### File: `src/acs_webclient/calls.py`

##### **Option A: Broadcast in `send_audio()` method**

**Current Code** (lines 108-111):
```python
async def send_audio(self, participant_id: str, pcm_bytes: bytes, timestamp_ms: int | None) -> None:
    if not self.upstream:
        return
    payload = build_audio_message(participant_id, pcm_bytes, timestamp_ms)
    await self.upstream.send_json(payload)
```

**Proposed Change**:
```python
async def send_audio(self, participant_id: str, pcm_bytes: bytes, timestamp_ms: int | None) -> None:
    if not self.upstream:
        return

    # Send to upstream translation service
    payload = build_audio_message(participant_id, pcm_bytes, timestamp_ms)
    await self.upstream.send_json(payload)

    # Broadcast original audio to other participants (not sender)
    await self.broadcast_audio_to_others(participant_id, pcm_bytes, timestamp_ms)
```

##### **Add New Method: `broadcast_audio_to_others()`**

```python
async def broadcast_audio_to_others(
    self,
    sender_participant_id: str,
    pcm_bytes: bytes,
    timestamp_ms: int | None
) -> None:
    """
    Broadcast original audio from one participant to all others.
    Excludes the sender to avoid echo.
    """
    # Build audio message in ACS format
    audio_payload = {
        "kind": "audioData",
        "audioData": {
            "participantRawID": sender_participant_id,
            "timestamp": iso_timestamp(timestamp_ms),
            "data": base64.b64encode(pcm_bytes).decode("ascii"),
            "silent": False,
        },
        "stopAudio": None,
    }

    # Send to all participants except the sender
    inactive = []
    for participant_id, websocket in self.participants.items():
        if participant_id == sender_participant_id:
            continue  # Skip sender

        try:
            await websocket.send_json(audio_payload)
        except Exception:
            logger.info("Failed to send audio to participant %s", participant_id)
            inactive.append(participant_id)

    # Clean up disconnected participants
    for participant_id in inactive:
        self.participants.pop(participant_id, None)
```

**Import Required**:
```python
from datetime import datetime, timezone
import base64

def iso_timestamp(timestamp_ms: int | None = None) -> str:
    if timestamp_ms is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
```

---

### 2. Message Format

The broadcast will use the same format as upstream audio responses:

```json
{
  "kind": "audioData",
  "audioData": {
    "participantRawID": "Alice",
    "timestamp": "2026-01-11T19:45:07.841547Z",
    "data": "BASE64_ENCODED_PCM_AUDIO",
    "silent": false
  },
  "stopAudio": null
}
```

**Why this format?**
- ✅ Frontend already handles this format (existing `handleInbound()` logic)
- ✅ Consistent with upstream translation responses
- ✅ No frontend changes required
- ✅ Includes participant identification via `participantRawID`

---

### 3. Frontend Changes

**No changes required!** The frontend already handles `audioData` messages in `call-room.js`:

```javascript
// Existing code (lines 166-195)
const isAudioData = (kind === "audiodata" || type === "audiodata") && ...

if (isAudioData) {
  const base64Data = payload.audioData?.data || payload.data;
  const bytes = bytesFromBase64(base64Data);
  await this.playback.enqueue(bytes);
  // Audio plays automatically
}
```

**How it works**:
- Original audio from other participants arrives as `audioData` messages
- Frontend decodes base64 → PCM bytes
- `PlaybackQueue` schedules and plays audio
- Web Audio API mixes multiple audio sources automatically

---

## Considerations & Trade-offs

### ✅ Advantages

1. **Simple Implementation**: Reuses existing message format
2. **No Frontend Changes**: Works with current audio handling
3. **Proper Attribution**: `participantRawID` identifies speaker
4. **Automatic Mixing**: Web Audio API handles concurrent playback
5. **No Echo**: Sender excluded from broadcast

### ⚠️ Potential Issues

1. **Bandwidth Usage**:
   - Each participant receives N-1 original audio streams
   - Plus translated audio from upstream
   - **Mitigation**: Audio is compressed (16 kHz PCM16, ~32 kbps per stream)

2. **Audio Overlap**:
   - If 3 people speak simultaneously, each hears 2 original + 3 translations = 5 streams
   - **Mitigation**: This is expected behavior for conference calls
   - **Alternative**: Add silence detection to mute non-speaking participants

3. **Latency**:
   - Original audio arrives faster than translations
   - Users hear original voice → then translation (delayed)
   - **Mitigation**: This is expected and natural

4. **Sample Rate Mismatch**:
   - Participants may send 16 kHz audio
   - Upstream may respond with 24 kHz audio
   - **Mitigation**: Frontend already resamples in `PlaybackQueue`

---

## Testing Strategy

### Unit Testing

1. **Test `broadcast_audio_to_others()`**:
   ```python
   async def test_broadcast_excludes_sender():
       # Add 3 participants: Alice, Bob, Charlie
       # Alice sends audio
       # Verify: Bob and Charlie receive, Alice doesn't
   ```

2. **Test disconnected participant handling**:
   ```python
   async def test_broadcast_handles_disconnected():
       # Add 2 participants, disconnect one
       # Send audio from remaining participant
       # Verify: No exceptions, disconnected removed
   ```

### Integration Testing

1. **Single Participant**:
   - Join call alone
   - Speak
   - Expected: No original audio broadcast (no other participants)
   - Expected: Hear own translation from upstream

2. **Two Participants**:
   - Alice and Bob join
   - Alice speaks
   - Expected (Alice): Hears own translation
   - Expected (Bob): Hears Alice's original + Alice's translation

3. **Three+ Participants**:
   - Alice, Bob, Charlie join
   - All speak simultaneously
   - Expected: Each hears 2 original streams + 3 translations

4. **Participant Leave/Join Mid-Call**:
   - Start with 2 participants
   - Third joins while first is speaking
   - Expected: Third hears ongoing audio immediately

---

## Performance Considerations

### Message Rate

For 3 participants, each speaking:

| Source | Messages/sec | Bandwidth (per participant) |
|--------|--------------|------------------------------|
| Own audio to backend | ~62 (16 kHz ÷ 256 samples) | Upload: ~32 kbps |
| Original audio from 2 others | ~124 | Download: ~64 kbps |
| Translations from upstream | ~124 | Download: ~64 kbps |
| **Total** | **~248 msgs/sec** | **~128 kbps down + 32 kbps up** |

**Verdict**: Acceptable for modern networks (typical broadband: 10+ Mbps)

---

## Alternative Approaches

### Alternative 1: Separate Message Type

Create a new message type `participant.audio`:

```json
{
  "type": "participant.audio",
  "participant_id": "Alice",
  "data": "BASE64_PCM",
  "timestamp_ms": 1234567890
}
```

**Pros**:
- Clearer distinction between original and translated audio
- Could add metadata (e.g., `is_speaking` flag)

**Cons**:
- Requires frontend changes to handle new message type
- Duplicates existing audio handling logic

**Recommendation**: ❌ Not worth the complexity

---

### Alternative 2: Server-Side Audio Mixing

Backend mixes all participant audio before broadcasting:

**Pros**:
- Reduces bandwidth (1 stream instead of N)
- Simpler client-side

**Cons**:
- Requires audio processing library (e.g., pydub, ffmpeg)
- Adds latency
- Loses per-participant identification
- Complex implementation

**Recommendation**: ❌ Overkill for this use case

---

## Implementation Checklist

### Backend (`calls.py`)

- [ ] Add `iso_timestamp()` helper function (or import from `protocol.acs`)
- [ ] Add `broadcast_audio_to_others()` method to `CallState`
- [ ] Update `send_audio()` to call broadcast method
- [ ] Add logging for broadcast success/failure
- [ ] Handle disconnected participants gracefully

### Testing

- [ ] Unit test: Broadcast excludes sender
- [ ] Unit test: Handles disconnected participants
- [ ] Integration test: 2 participants hear each other
- [ ] Integration test: 3+ participants all hear each other
- [ ] Load test: 5+ participants speaking simultaneously

### Documentation

- [ ] Update README with new behavior
- [ ] Document expected audio flow
- [ ] Add troubleshooting guide for audio overlap issues

---

## Rollout Plan

### Phase 1: Development
1. Implement backend changes
2. Add unit tests
3. Test with 2 participants locally

### Phase 2: Testing
1. Deploy to dev environment
2. Multi-participant integration tests
3. Monitor backend logs for errors
4. Check frontend console for audio playback issues

### Phase 3: Production
1. Deploy to production
2. Monitor bandwidth usage
3. Collect user feedback on audio quality
4. Consider adding toggle to disable original audio if needed

---

## Expected Outcome

After implementation:

1. **Alice speaks** → Bob hears:
   - Alice's original voice (16 kHz, low latency)
   - Alice's translated voice (via upstream, slight delay)

2. **Multi-speaker scenario**:
   - Natural conference call experience
   - Translations overlay on original audio
   - Web Audio API handles mixing

3. **Performance**:
   - ~128 kbps download per participant (acceptable)
   - No frontend changes needed
   - Minimal backend complexity

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Audio overlap confusion | Medium | Medium | Add participant name to event log on speak |
| Bandwidth issues | Low | Medium | Already using compressed audio |
| Echo/feedback | Low | High | Sender excluded from broadcast ✅ |
| Race conditions | Low | High | Already using locks in `send_audio()` ✅ |
| Disconnected participant errors | Medium | Low | Exception handling in broadcast loop ✅ |

---

## Conclusion

**Recommendation**: ✅ Implement Option A (broadcast in `send_audio()`)

- Simple, clean implementation
- Reuses existing infrastructure
- No frontend changes required
- Low risk, high value

**Estimated Effort**: 2-3 hours
- Backend changes: 1 hour
- Testing: 1-2 hours
- Documentation: 30 minutes

**Next Steps**:
1. Review and approve this plan
2. Implement backend changes
3. Test with multiple participants
4. Deploy and monitor
