# WebSocket Server API Documentation

This document describes how external applications can connect to the WebSocket server to send audio data for translation processing.

## Overview

The WebSocket server accepts incoming connections and receives audio data that will be processed and sent to Azure Speech Translation services. The server is designed to handle both binary audio data and JSON control messages.

## Starting the Server

Start the WebSocket server using the CLI:

```bash
speech-poc serve --host localhost --port 8765 --from-language en-US --to-language es
```

### Server Options

- `--host` / `-h`: Host address to bind (default: `localhost`)
- `--port` / `-p`: Port number (default: `8765`)
- `--from-language` / `-f`: Source language locale (default: `en-US`)
- `--to-language` / `-t`: Target language(s) (default: `es`)
- `--voice` / `-v`: Optional neural voice for synthesis
- `--dotenv-path`: Optional path to `.env` file

## Connection Details

- **Protocol**: WebSocket (ws:// or wss://)
- **Default Endpoint**: `ws://localhost:8765`
- **Connection Type**: Full-duplex bidirectional communication

## Message Formats

### Binary Messages (Audio Data)

Send raw audio data as binary WebSocket messages. The server expects audio in a format compatible with Azure Speech services.

**Recommended Format:**
- **Sample Rate**: 16 kHz (16000 Hz)
- **Channels**: Mono (1 channel)
- **Bit Depth**: 16-bit PCM
- **Byte Order**: Little-endian

**Example (Python):**
```python
import websockets
import wave

async def send_audio_file(uri: str, audio_path: str):
    async with websockets.connect(uri) as websocket:
        with wave.open(audio_path, 'rb') as wav_file:
            # Read audio data in chunks
            chunk_size = 3200  # 100ms at 16kHz, 16-bit mono
            while True:
                audio_chunk = wav_file.readframes(chunk_size)
                if not audio_chunk:
                    break
                await websocket.send(audio_chunk)
                # Wait for acknowledgment
                response = await websocket.recv()
                print(f"Server response: {response}")
```

### JSON Messages (Control/Text)

Send JSON-encoded text messages for control commands or text input.

**Message Format:**
```json
{
  "type": "command_or_data",
  "data": "..."
}
```

**Example (Python):**
```python
import websockets
import json

async def send_json_message(uri: str):
    async with websockets.connect(uri) as websocket:
        message = {
            "type": "text_input",
            "data": "Hello, this is a test message"
        }
        await websocket.send(json.dumps(message))
        response = await websocket.recv()
        print(f"Server response: {response}")
```

## Server Responses

The server sends acknowledgment responses after receiving messages:

**Response Format:**
```json
{
  "status": "received",
  "message": "Data received, processing will be implemented"
}
```

## Connection Lifecycle

1. **Connect**: Establish WebSocket connection to `ws://host:port`
2. **Send Data**: Send binary audio chunks or JSON messages
3. **Receive Acknowledgments**: Server responds with status messages
4. **Disconnect**: Close connection when done

## Example Implementations

### Python Client

```python
import asyncio
import websockets
import json
import wave

async def translate_audio(uri: str, audio_file: str):
    """Send audio file for translation."""
    async with websockets.connect(uri) as websocket:
        print(f"Connected to {uri}")
        
        # Send audio file
        with wave.open(audio_file, 'rb') as wav:
            print(f"Sending audio: {audio_file}")
            chunk_size = 3200  # 100ms chunks
            
            while True:
                chunk = wav.readframes(chunk_size)
                if not chunk:
                    break
                
                await websocket.send(chunk)
                response = await websocket.recv()
                print(f"Response: {response}")
        
        print("Audio transmission complete")

# Run the client
asyncio.run(translate_audio("ws://localhost:8765", "audio.wav"))
```

### JavaScript/Node.js Client

```javascript
const WebSocket = require('ws');
const fs = require('fs');

function sendAudioFile(uri, audioFile) {
    const ws = new WebSocket(uri);
    
    ws.on('open', () => {
        console.log(`Connected to ${uri}`);
        
        // Read and send audio file
        const audioBuffer = fs.readFileSync(audioFile);
        const chunkSize = 3200; // 100ms at 16kHz, 16-bit mono
        
        for (let i = 0; i < audioBuffer.length; i += chunkSize) {
            const chunk = audioBuffer.slice(i, i + chunkSize);
            ws.send(chunk);
        }
        
        console.log('Audio transmission complete');
    });
    
    ws.on('message', (data) => {
        console.log('Server response:', data.toString());
    });
    
    ws.on('error', (error) => {
        console.error('WebSocket error:', error);
    });
}

// Usage
sendAudioFile('ws://localhost:8765', 'audio.wav');
```

### JavaScript/Browser Client

```javascript
function connectToTranslationServer(uri) {
    const ws = new WebSocket(uri);
    
    ws.onopen = () => {
        console.log('Connected to translation server');
        
        // Send text message
        const message = {
            type: 'text_input',
            data: 'Hello, translate this message'
        };
        ws.send(JSON.stringify(message));
    };
    
    ws.onmessage = (event) => {
        const response = JSON.parse(event.data);
        console.log('Server response:', response);
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
    
    ws.onclose = () => {
        console.log('Connection closed');
    };
    
    return ws;
}

// Usage
const ws = connectToTranslationServer('ws://localhost:8765');
```

## Error Handling

The server handles various connection scenarios:

- **Clean Disconnection**: Server logs a clean disconnect message
- **Error Disconnection**: Server logs error details
- **Connection Errors**: Server logs exceptions and continues running

Clients should implement appropriate error handling:

```python
try:
    async with websockets.connect(uri) as websocket:
        # Send data
        pass
except websockets.exceptions.ConnectionClosedError as e:
    print(f"Connection closed with error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Audio Format Requirements

For best compatibility with Azure Speech services:

- **WAV Format**: PCM, 16-bit, mono, 16 kHz
- **Chunk Size**: Send in 100ms chunks (3200 bytes at 16kHz, 16-bit mono) for real-time streaming
- **Endianness**: Little-endian byte order

### Converting Audio to Required Format

**Using FFmpeg:**
```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 -acodec pcm_s16le output.wav
```

**Using Python (pydub):**
```python
from pydub import AudioSegment

audio = AudioSegment.from_file("input.mp3")
audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
audio.export("output.wav", format="wav")
```

## Security Considerations

- The default server binds to `localhost` for security
- For production use, consider:
  - Using `wss://` (WebSocket Secure) with TLS
  - Implementing authentication/authorization
  - Rate limiting and connection management
  - Network firewall rules

## Future Enhancements

The following features are planned for future iterations:

- Audio processing and translation pipeline integration
- Real-time translation result streaming
- Session management and multi-client support
- Error recovery and retry mechanisms
- Audio format auto-detection and conversion

## Troubleshooting

### Connection Refused
- Verify the server is running: `speech-poc serve`
- Check host and port settings match between server and client
- Ensure firewall allows connections on the specified port

### No Response from Server
- Check server console for error messages
- Verify message format (binary or valid JSON)
- Ensure connection is established before sending data

### Audio Format Issues
- Verify audio is 16 kHz, mono, 16-bit PCM
- Check audio file is not corrupted
- Ensure proper byte order (little-endian)

## Support

For issues or questions:
1. Check server console output for error messages
2. Verify Azure credentials are configured correctly
3. Review the main [README.md](README.md) for configuration details

