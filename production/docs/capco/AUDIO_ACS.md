# ACS Outbound Audio WebSocket Frame Specification

## 1. Purpose

This document defines the **canonical outbound WebSocket frame** used to send **audio from the gateway to Azure Communication Services (ACS)** for bidirectional media streaming.

It is intentionally minimal and strict. Anything not explicitly listed here **must not** be sent to ACS.

---

## 2. Transport

- **Protocol:** WebSocket
- **Direction:** Gateway → ACS
- **Encoding:** UTF-8 JSON text frame
- **One frame = one audio chunk**

---

## 3. Frame Shape (Audio Data)

### Required JSON structure

```json
{
  "kind": "audioData",
  "audioData": {
    "data": "<base64 PCM bytes>",
    "timestamp": null,
    "participant": null,
    "isSilent": false
  },
  "stopAudio": null
}
```

---

## 4. Field Definitions

### Top-level fields

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `kind` | string | Yes | Must be exactly `"audioData"` |
| `audioData` | object | Yes | Audio payload container |
| `stopAudio` | null | Yes | Must be `null` for audio frames |

---

### `audioData` object

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `data` | string | Yes | Base64-encoded raw PCM audio bytes |
| `timestamp` | string \| null | Yes | Always `null` for outbound audio |
| `participant` | string \| null | Yes | Always `null` (ACS routes audio automatically) |
| `isSilent` | boolean | Yes | `false` for normal audio |

---

## 5. Audio Format Requirements

The audio in `audioData.data` **must exactly match** the format declared earlier by ACS via the inbound `AudioMetadata` message.

Typical ACS audio format:

- Encoding: PCM
- Bit depth: 16-bit (PCM16)
- Endianness: Little-endian
- Sample rate: 16000 Hz
- Channels: 1 (mono)

---

