# System Information Message Specification

This document defines the WebSocket message format for querying system information from the translation service.

## Overview

The system information protocol allows test runners to query the translation service for its configuration, version, and runtime environment details. This information is captured during evaluation runs and stored in MongoDB for reproducibility and debugging.

## Message Namespace

System information messages use the **control message namespace**:
- **Request**: `control.test.request.system_info`
- **Response**: `control.test.response.system_info`

This namespace follows the pattern: `control.<domain>.<direction>.<action>`

## Message Flow

```
Test Runner                             Translation Service
     |                                         |
     |---(1) control.test.request.system_info->|
     |                                         |
     |<--(2) control.test.response.system_info-|
     |                                         |
```

## Message Types

### 1. System Information Request

Sent by the test runner to request system information from the translation service.

**Message Type**: `control.test.request.system_info`

**Direction**: Client → Server (Test Runner → Translation Service)

**Format**:

```json
{
  "type": "control.test.request.system_info",
  "timestamp": "2025-12-09T16:30:00.000Z"
}
```

**Fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✓ | Message type identifier. Must be `"control.test.request.system_info"` |
| `timestamp` | string | ✓ | ISO 8601 timestamp when the request was sent |

**Example**:

```json
{
  "type": "control.test.request.system_info",
  "timestamp": "2025-12-09T16:30:00.123456Z"
}
```

---

### 2. System Information Response

Sent by the translation service in response to a system information request.

**Message Type**: `control.test.response.system_info`

**Direction**: Server → Client (Translation Service → Test Runner)

**Format**:

```json
{
  "type": "control.test.response.system_info",
  "timestamp": "2025-12-09T16:30:00.234Z",
  "system_info": {
    "service": {
      "name": "Azure Speech Translation Service",
      "version": "1.2.3",
      "build": "2025.12.05.1"
    },
    "configuration": {
      "supported_languages": ["en-US", "es-ES", "de-DE", "fr-FR"],
      "audio_format": {
        "encoding": "PCM",
        "sample_rate": 16000,
        "channels": 1,
        "sample_width": 2
      },
      "features": {
        "personal_voice": true,
        "streaming": true,
        "text_delta": true
      }
    },
    "runtime": {
      "region": "eastus",
      "instance_id": "acs-instance-abc123",
      "uptime_seconds": 86400
    }
  }
}
```

**Fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✓ | Message type identifier. Must be `"control.test.response.system_info"` |
| `timestamp` | string | ✓ | ISO 8601 timestamp when the response was sent |
| `system_info` | object | ✓ | System information payload (translation system dependent - see below) |

---

## System Info Payload

### Important Notes

**The `system_info` payload is translation system dependent and not standardized.**

The test framework:
- ✓ **Does NOT parse** or interpret the payload structure
- ✓ **Stores verbatim** in MongoDB for reference
- ✓ **Uses only for** test reproduction and debugging

Translation services are free to include any relevant information in the payload. The structure below is **suggestive only** and provides common fields that may be useful for debugging and reproducing test results.

---

### Suggested Payload Structure

The following structure provides hints for useful information, but **none of these fields are required or enforced**:

#### `service` (optional object)
Suggested information about the translation service itself.

| Field | Type | Suggested Use |
|-------|------|---------------|
| `name` | string | Service name (e.g., "Azure Speech Translation Service", "Custom Translation API") |
| `version` | string | Semantic version (e.g., "1.2.3") |
| `build` | string | Build identifier, commit hash, or build date |
| `provider` | string | Service provider (e.g., "Azure", "AWS", "Custom") |

#### `configuration` (optional object)
Suggested service configuration and capabilities.

| Field | Type | Suggested Use |
|-------|------|---------------|
| `supported_languages` | array[string] | Language codes the service supports |
| `audio_format` | object | Audio format requirements (encoding, sample rate, channels) |
| `features` | object | Feature flags (personal_voice, streaming, text_delta, etc.) |
| `model` | string | Translation model identifier or version |
| `endpoint` | string | Service endpoint URL (if applicable) |

**Example `audio_format`** (if included):

| Field | Type | Suggested Use |
|-------|------|---------------|
| `encoding` | string | Audio encoding (e.g., "PCM", "OPUS", "MP3") |
| `sample_rate` | integer | Sample rate in Hz (e.g., 16000, 24000) |
| `channels` | integer | Number of audio channels (1=mono, 2=stereo) |
| `sample_width` | integer | Bytes per sample (2=16-bit, 4=32-bit) |

**Example `features`** (if included):

| Field | Type | Suggested Use |
|-------|------|---------------|
| `personal_voice` | boolean | Personal Voice synthesis capability |
| `streaming` | boolean | Streaming translation capability |
| `text_delta` | boolean | Incremental text delta support |
| `bidirectional` | boolean | Bidirectional translation support |

#### `runtime` (optional object)
Suggested runtime environment and deployment information.

| Field | Type | Suggested Use |
|-------|------|---------------|
| `region` | string | Deployment region (e.g., "eastus", "westus", "us-west-2") |
| `instance_id` | string | Instance/container identifier for debugging |
| `uptime_seconds` | integer | Service uptime in seconds |
| `environment` | string | Environment name (e.g., "production", "staging", "dev") |
| `deployed_at` | string | Deployment timestamp (ISO 8601) |

#### Additional Custom Fields

Translation systems may include **any additional fields** relevant to their implementation:
- Model parameters (temperature, beam size, etc.)
- Feature flags specific to the service
- Infrastructure details (Kubernetes cluster, Azure region, etc.)
- Performance metrics (request count, average latency, etc.)
- License or subscription information
- Debug flags or trace IDs

---

### Example Responses

#### Example 1: Azure Speech Translation Service

```json
{
  "type": "control.test.response.system_info",
  "timestamp": "2025-12-09T16:30:00.234567Z",
  "system_info": {
    "service": {
      "name": "Azure Speech Translation Service",
      "version": "2.5.1",
      "build": "2025.12.01.3",
      "provider": "Azure"
    },
    "configuration": {
      "supported_languages": ["en-US", "es-ES", "de-DE", "fr-FR", "ja-JP", "zh-CN"],
      "audio_format": {
        "encoding": "PCM",
        "sample_rate": 16000,
        "channels": 1,
        "sample_width": 2
      },
      "features": {
        "personal_voice": true,
        "streaming": true,
        "text_delta": true
      }
    },
    "runtime": {
      "region": "eastus",
      "instance_id": "acs-prod-eastus-001",
      "uptime_seconds": 432000,
      "environment": "production"
    }
  }
}
```

#### Example 2: Custom Translation Service (Minimal)

```json
{
  "type": "control.test.response.system_info",
  "timestamp": "2025-12-09T16:30:00.234567Z",
  "system_info": {
    "service": {
      "name": "Custom Translation API",
      "version": "1.0.0"
    }
  }
}
```

#### Example 3: Custom Translation Service (Extended)

```json
{
  "type": "control.test.response.system_info",
  "timestamp": "2025-12-09T16:30:00.234567Z",
  "system_info": {
    "service": {
      "name": "vt Translation Service",
      "version": "3.2.1",
      "build": "f4a3b2c",
      "provider": "Custom"
    },
    "configuration": {
      "model": "whisper-large-v3",
      "translation_engine": "neural-mt-v2",
      "supported_languages": ["en-US", "es-ES", "de-DE"],
      "max_audio_duration_seconds": 300,
      "custom_features": {
        "medical_terminology": true,
        "speaker_diarization": false,
        "quality_mode": "high"
      }
    },
    "runtime": {
      "environment": "staging",
      "deployed_at": "2025-12-01T10:00:00Z",
      "kubernetes_cluster": "k8s-prod-us-west-2",
      "pod_name": "translation-service-7d4f8b9c-xk2l9"
    },
    "custom_metadata": {
      "git_commit": "f4a3b2c1d5e6f7g8h9i0j1k2l3m4n5o6",
      "debug_mode": false,
      "trace_id": "abc123-xyz789"
    }
  }
}
```

---

## Error Handling

### Timeout

If the translation service does not respond within the configured timeout (default: 5 seconds), the test runner will:
- Log a warning
- Continue without translation system information
- Store only test runner information in the evaluation run

### Unsupported Feature

If the translation service does not support system information queries:
- No response will be received
- Request will timeout gracefully
- System information will be marked as unavailable

### Malformed Response

If the response is malformed (invalid JSON or missing `type` field):
- Log an error with the raw response
- Treat system info as unavailable
- Do not fail the test run

**Note**: Since the `system_info` payload structure is not standardized, any valid JSON object is acceptable. The test framework will store it verbatim regardless of structure.
