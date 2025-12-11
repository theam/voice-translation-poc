# Translation Text Message Specification

This document defines the WebSocket message format for receiving translated text from the translation service. These messages are the primary output used for evaluating translation quality through metrics like WER, completeness, and intent preservation.

## Overview

The translation service sends text translations through incremental delta updates using the **control message namespace**:

- **`control.test.response.text_delta`** - Incremental translation updates (streaming)

These messages are captured during test execution and compared against expected translations defined in scenario YAML files to measure translation accuracy and quality.

## Message Namespace

Translation text messages use the **control message namespace**:
- **Response**: `control.test.response.text_delta`

This namespace follows the pattern: `control.<domain>.<direction>.<action>`

## Message Flow

```
Test Runner                             Translation Service
     |                                         |
     |-------(sends audio frames)------------->|
     |                                         |
     |                                         | (processing audio + translating)
     |                                         |
     |<--(control.test.response.text_delta)----|  "El"
     |<--(control.test.response.text_delta)----|  " paciente"
     |<--(control.test.response.text_delta)----|  " se presenta..."
     |                                         |
```

## Message Type

### Translation Text Delta Message (Incremental Updates)

Sent by the translation service with incremental text updates as translation progresses. The test framework buffers these deltas to reconstruct the complete translation.

**Message Type**: `control.test.response.text_delta`

**Direction**: Server → Client (Translation Service → Test Runner)

**Format**:

```json
{
  "type": "control.test.response.text_delta",
  "participant_id": "doctor_turn_1",
  "delta": "The patient ",
  "timestamp_ms": 1523
}
```

**Fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✓ | Message type identifier. Must be `"control.test.response.text_delta"` |
| `participant_id` | string | ✓ | Identifier for the participant/speaker (matches event ID from test scenario) |
| `delta` | string | ✓ | Incremental text fragment to append to buffered translation |
| `timestamp_ms` | integer | ○ | Timestamp in milliseconds |

**Delta Buffering**:

The test framework maintains separate buffers for each participant/turn, keyed by `participant_id`.

**Important**: Each delta message contains only a **portion** of the complete translation. The test framework assembles multiple delta messages by appending them to the appropriate buffer. The final buffered text is used for metrics evaluation.

**Example - Incremental Translation Stream**:

```json
// Delta 1 - First portion of translation
{
  "type": "control.test.response.text_delta",
  "participant_id": "doctor_turn_1",
  "delta": "The ",
  "timestamp_ms": 1200
}

// Delta 2 - Appended to buffer for doctor_turn_1
{
  "type": "control.test.response.text_delta",
  "participant_id": "doctor_turn_1",
  "delta": "patient ",
  "timestamp_ms": 1350
}

// Delta 3 - Appended to buffer for doctor_turn_1
{
  "type": "control.test.response.text_delta",
  "participant_id": "doctor_turn_1",
  "delta": "presents with fever",
  "timestamp_ms": 1520
}

// Assembled result in buffer: "The patient presents with fever"
```

### Example - Multi-Participant Deltas

```json
// Doctor's translation (participant_id: "doctor_turn_1")
{"type": "control.test.response.text_delta", "participant_id": "doctor_turn_1", "delta": "The patient "}
{"type": "control.test.response.text_delta", "participant_id": "doctor_turn_1", "delta": "has fever"}

// Patient's translation (participant_id: "patient_turn_1")
{"type": "control.test.response.text_delta", "participant_id": "patient_turn_1", "delta": "I have "}
{"type": "control.test.response.text_delta", "participant_id": "patient_turn_1", "delta": "a headache"}

// Result: Two separate buffers
// doctor_turn_1: "The patient has fever"
// patient_turn_1: "I have a headache"
```