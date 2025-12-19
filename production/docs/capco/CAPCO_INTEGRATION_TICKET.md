# Capco Translation Service - Evaluation Framework Integration

## Description

Integrate Capco Translation Service with the Production Evaluation Framework by implementing control message protocol support.

## Overview

The evaluation framework tests translation quality through automated scenario execution. To enable testing, the translation service must implement two WebSocket message types in the control namespace:

1. **System Information** - Respond to test runner queries about service configuration
2. **Translation Text Deltas** - Stream incremental translation updates for quality metrics

## Requirements

### 1. System Info Response (`control.test.response.system_info`)

- Listen for `control.test.request.system_info` messages
- Respond with service metadata (name, version, configuration, etc.)
- Payload structure is flexible - include any relevant debugging information
- Handle requests asynchronously without blocking translation pipeline

### 2. Translation Text Deltas (`control.test.response.text_delta`)

- Send incremental translation updates as text becomes available
- Include `participant_id` to identify the speaker/turn
- Each delta contains a portion of the translation (assembled by receiver)
- Low-latency streaming as translation progresses

## Implementation Notes

- Both message types use the `control.test.*` namespace
- System info payload is opaque to framework (stored verbatim for debugging)
- Text deltas are buffered by `participant_id` and used for metrics evaluation
- See referenced specifications for complete message formats and examples

## Acceptance Criteria

- [ ] Service responds to `control.test.request.system_info` with valid JSON payload
- [ ] Service sends `control.test.response.text_delta` messages during translation
- [ ] Delta messages include required `participant_id` field
- [ ] Multiple deltas for same participant are correctly ordered/timestamped
- [ ] Integration tested with production evaluation framework scenarios

## Specifications

**Reference Documents:**
- `SYSTEM_INFO_MESSAGES.md` - System information protocol specification
- `TRANSLATION_TEXT_MESSAGES.md` - Translation delta protocol specification

## Integration Benefits

Once implemented, the Capco Translation Service will support:
- Automated quality metrics (WER, completeness, intent preservation, etc.)
- Scenario-based regression testing
- Historical performance tracking with MongoDB storage
- A/B testing of translation improvements
- Compliance audit trails for healthcare translation accuracy
