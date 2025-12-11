# WebSocket Audio Emitter

This directory contains a test client for sending audio data and JSON messages to the translation WebSocket server.

## Overview

The `emit_audio.py` script connects to the WebSocket server and can send:
- **Audio files** (WAV files) for translation processing
- **Microphone streaming** (real-time audio capture) for live translation
- **JSON control messages** for text input or commands

All audio is sent using the official ACS (Azure Communication Services) JSON format with base64-encoded PCM audio data.

## Prerequisites

The script requires the `websockets` library, which is already included in the main project dependencies. If running this script independently, install it with:

```bash
pip install websockets
```

For microphone streaming, you also need `sounddevice` and `numpy`:

```bash
pip install sounddevice numpy
```

Or if using Poetry from the project root:

```bash
poetry install
# For microphone support:
pip install sounddevice numpy
```

**Note**: When using Poetry, you can run the script with:

```bash
poetry run python test-socket-emitter/emit_audio.py --audio samples/harvard.wav
poetry run python test-socket-emitter/emit_audio.py --microphone
```

## Connection Configuration

### Default Settings

- **Host**: `localhost`
- **Port**: `8765`
- **Protocol**: `ws://` (WebSocket)

### Custom Configuration

You can override the default connection settings using command-line arguments:

- `--host`: WebSocket server host address
- `--port`: WebSocket server port number

## Data Format Requirements

### Audio Files

The server expects audio in the following format:

- **Format**: WAV (PCM)
- **Sample Rate**: 16 kHz (16000 Hz) - recommended
- **Channels**: Mono (1 channel)
- **Bit Depth**: 16-bit PCM
- **Byte Order**: Little-endian

**Note**: The script will attempt to send any WAV file, but audio that doesn't match the recommended format may not process correctly on the server side.

### ACS Format (Azure Communication Services-like)

When using the `--acs-format` flag, audio is sent in a JSON structure that mimics Azure Communication Services real-time media streaming format. The audio data is base64-encoded and wrapped in an event structure:

```json
{
  "id": "unique-event-id",
  "eventType": "Microsoft.Communication.MediaStream.AudioData",
  "eventTime": "2025-01-15T10:30:00.000Z",
  "data": {
    "messageId": "timestamp-based-id",
    "participantId": "8:acs:user-id",
    "audioData": {
      "format": "pcm",
      "sampleRate": 16000,
      "channels": 1,
      "bitsPerSample": 16,
      "data": "base64-encoded-audio-chunk",
      "timestamp": "2025-01-15T10:30:00.000Z",
      "sequenceNumber": 0
    },
    "metadata": {
      "source": "test-emitter",
      "chunkSize": 3200
    }
  },
  "dataVersion": "1.0"
}
```

This format includes:
- **Event metadata**: Unique event ID, event type, and timestamp
- **Participant information**: Participant/sender ID (auto-generated if not provided)
- **Audio data**: Base64-encoded PCM audio with format specifications
- **Sequence numbers**: Chunk sequence numbers for ordering
- **Metadata**: Additional information about the audio chunk

### JSON Messages

JSON messages should follow this structure:

```json
{
  "type": "message_type",
  "data": "message content"
}
```

Common message types:
- `text_input`: Text to be translated
- `command`: Control commands (implementation-dependent)

## CLI Commands

### Sending Audio Files

Audio files are automatically converted to 16kHz, 16-bit, mono PCM format and sent using the official ACS JSON format.

**Basic usage:**
```bash
python emit_audio.py --audio samples/harvard.wav
```

**With custom host and port:**
```bash
python emit_audio.py --audio samples/harvard.wav --host localhost --port 9000
```

**With verbose output:**
```bash
python emit_audio.py --audio samples/harvard.wav --verbose
```

**Custom chunk size (for streaming):**
```bash
python emit_audio.py --audio samples/harvard.wav --chunk-size 6400
```

**With custom participant ID:**
```bash
python emit_audio.py --audio samples/harvard.wav --participant-id "4:+34646783858"
```

### Streaming from Microphone

Stream live audio from your microphone to the server for real-time translation. Audio is automatically captured at 16kHz, 16-bit, mono PCM and sent in ACS JSON format.

**Basic microphone streaming (continuous until Ctrl+C):**
```bash
python emit_audio.py --microphone
```

**Microphone streaming with duration limit (10 seconds):**
```bash
python emit_audio.py --microphone --duration 10
```

**With verbose output:**
```bash
python emit_audio.py --microphone --verbose
```

**With custom participant ID:**
```bash
python emit_audio.py --microphone --participant-id "4:+34646783858"
```

**Custom chunk size:**
```bash
python emit_audio.py --microphone --chunk-size 6400
```

**Microphone to custom server:**
```bash
python emit_audio.py --microphone --host localhost --port 9000 --duration 30
```

### Sending JSON Messages

**Basic text input:**
```bash
python emit_audio.py --json --type text_input --data "Hello, translate this message"
```

**With custom host and port:**
```bash
python emit_audio.py --json --type text_input --data "Test message" --host localhost --port 9000
```

**With verbose output:**
```bash
python emit_audio.py --json --type text_input --data "Test message" --verbose
```

### Command-Line Options

```
--host HOST              WebSocket server host (default: localhost)
--port PORT              WebSocket server port (default: 8765)
--audio FILE             Path to WAV audio file to send (auto-converted to 16kHz, 16-bit, mono)
--microphone             Stream audio from microphone (16kHz, 16-bit, mono)
--json                   Send a JSON message instead of audio
--type TYPE              Message type for JSON mode (default: text_input)
--data DATA              Message data for JSON mode (required with --json)
--chunk-size SIZE        Audio chunk size in bytes (default: 3200 = 100ms at 16kHz)
--participant-id ID      Participant/sender ID for ACS format (auto-generated if not provided)
--duration SECONDS       Duration limit for microphone streaming (default: continuous until Ctrl+C)
--verbose, -v            Enable verbose output
```

**Notes:**
- All audio (files and microphone) is sent using the official ACS JSON format with base64-encoded PCM
- Audio files are automatically converted to the required format (16kHz, 16-bit, mono) using ffmpeg
- Microphone streaming requires `sounddevice` and `numpy` packages

## Usage Examples

### Example 1: Send a Sample Audio File

```bash
# From the project root (using system Python)
python test-socket-emitter/emit_audio.py --audio samples/harvard.wav

# Or using Poetry
poetry run python test-socket-emitter/emit_audio.py --audio samples/harvard.wav
```

Expected output:
```
✓ Connected to ws://localhost:8765
Sending audio: harvard.wav
✓ Audio transmission complete
  - Total chunks: 45
  - Total bytes: 144000
```

### Example 1a: Stream from Microphone

```bash
# Stream from microphone for 10 seconds
python test-socket-emitter/emit_audio.py --microphone --duration 10 --verbose
```

Expected output:
```
✓ Connected to ws://localhost:8765
Microphone streaming info:
  - Sample rate: 16000 Hz
  - Channels: 1 (mono)
  - Bits per sample: 16
  - Chunk size: 3200 bytes (~100ms)
  - Format: ACS JSON with PCM 16-bit
  - Duration limit: 10 seconds
  Generated participant ID: 4:+a1b2c3d4e5f
✓ Microphone stream started
Starting microphone capture... (press Ctrl+C to stop)
  Chunk 0: 3200 bytes (base64: 4268 chars)
  Chunk 1: 3200 bytes (base64: 4268 chars)
  ...

✓ Duration limit reached (10s)
✓ Microphone streaming complete
  - Total chunks: 100
  - Total bytes: 320000
  - Duration: 10.02 seconds
  - Format: Official ACS JSON with base64-encoded audio
✓ Microphone stream stopped
```

### Example 2: Send a JSON Text Message

```bash
# Using system Python
python test-socket-emitter/emit_audio.py --json --type text_input --data "Hello, world"

# Or using Poetry
poetry run python test-socket-emitter/emit_audio.py --json --type text_input --data "Hello, world"
```

Expected output:
```
✓ Connected to ws://localhost:8765
Sending JSON message: type=text_input
✓ Server response: received
```

### Example 3: Verbose Audio Transmission

```bash
python test-socket-emitter/emit_audio.py --audio samples/speech_noise/clean/1.wav --verbose
```

This will show detailed information about:
- Audio file properties (sample rate, channels, duration)
- Each chunk sent and server responses
- Total transmission statistics

### Example 4: Custom Server Configuration

```bash
python test-socket-emitter/emit_audio.py \
  --audio samples/harvard.wav \
  --host 192.168.1.100 \
  --port 8765 \
  --verbose
```

## Audio Format Conversion

If your audio file is not in the required format, you can convert it using FFmpeg:

```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 -acodec pcm_s16le output.wav
```

Or using Python with pydub:

```python
from pydub import AudioSegment

audio = AudioSegment.from_file("input.mp3")
audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
audio.export("output.wav", format="wav")
```

## Error Handling

The script handles common error scenarios:

- **Connection refused**: Server is not running or wrong host/port
- **File not found**: Audio file path is incorrect
- **Invalid WAV file**: File is corrupted or not a valid WAV
- **Connection closed**: Server disconnected during transmission
- **Invalid JSON**: Server response is malformed

All errors are displayed with clear error messages and the script exits with a non-zero status code.

## Troubleshooting

### Connection Refused

**Problem**: `✗ Error: Connection refused`

**Solutions**:
1. Verify the server is running: `speech-poc serve --host localhost --port 8765`
2. Check that host and port match between server and client
3. Ensure firewall allows connections on the specified port

### Audio File Not Found

**Problem**: `✗ Error: Audio file not found: path/to/file.wav`

**Solutions**:
1. Use absolute paths or paths relative to the current working directory
2. Verify the file exists: `ls -la path/to/file.wav`
3. Check file permissions

### Invalid WAV File

**Problem**: `✗ Error: Invalid WAV file: ...`

**Solutions**:
1. Verify the file is a valid WAV file
2. Convert the audio to the required format (see Audio Format Conversion above)
3. Check file is not corrupted

### No Response from Server

**Problem**: Script hangs or shows timeout messages

**Solutions**:
1. Check server console for error messages
2. Verify message format (binary for audio, valid JSON for text)
3. Ensure connection is established before sending data
4. Check network connectivity

### Microphone Not Working

**Problem**: `✗ Error: sounddevice and numpy are required for microphone streaming`

**Solutions**:
1. Install required dependencies: `pip install sounddevice numpy`
2. On macOS, you may need to grant microphone permissions to Terminal/your IDE
3. Verify microphone is available: `python -c "import sounddevice as sd; print(sd.query_devices())"`

**Problem**: `✗ Error: Could not start microphone: ...`

**Solutions**:
1. Check that your microphone is connected and not in use by another application
2. Try listing available audio devices: `python -c "import sounddevice as sd; print(sd.query_devices())"`
3. On macOS, grant microphone permissions: System Preferences → Security & Privacy → Privacy → Microphone
4. On Linux, ensure your user is in the `audio` group: `sudo usermod -a -G audio $USER`
5. Try a different audio backend by setting environment variables (e.g., `SD_ENABLE_ASIO=1`)

**Problem**: Audio quality is poor or choppy

**Solutions**:
1. Increase chunk size: `--chunk-size 6400` (for 200ms chunks)
2. Check CPU usage - high CPU load can cause audio dropouts
3. Close other applications that might be using the microphone
4. Try reducing the number of verbose log messages

## Integration with Server

This client is designed to work with the WebSocket server started via:

```bash
speech-poc serve --host localhost --port 8765 --from-language en-US --to-language es
```

The server must be running before executing the client script.

## Script Location

The script can be run from anywhere, but typically from the project root:

```bash
# From project root
python test-socket-emitter/emit_audio.py --audio samples/harvard.wav

# Or from within the directory
cd test-socket-emitter
python emit_audio.py --audio ../samples/harvard.wav
```

## ACS Format Processing

For detailed information on how to process ACS-format audio streams in the WebSocket server, see:

- **[ACS_STREAM_PROCESSING.md](ACS_STREAM_PROCESSING.md)** - Complete specification for processing ACS-format streams, including detailed step-by-step instructions, error handling, and state management
- **[ACS_IMPLEMENTATION_GUIDE.md](ACS_IMPLEMENTATION_GUIDE.md)** - Quick implementation guide with code examples and integration patterns

These documents provide comprehensive guidance for implementing ACS format stream processing in the WebSocket server.

## See Also

- [WEBSOCKET_API.md](../WEBSOCKET_API.md) - Full WebSocket API documentation
- [README.md](../README.md) - Main project documentation

