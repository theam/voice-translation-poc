#!/usr/bin/env python3
"""
WebSocket echo server for Azure Communication Service AudioData messages.

Azure Communication Service uses WebSocket protocol, not raw TCP.
This server handles the WebSocket handshake and echoes audio messages.

Usage:
    python websocket_echo.py
    python websocket_echo.py --host 0.0.0.0 --port 8083
    poetry run websocket-echo
    poetry run websocket-echo --port 8083 --debug
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Optional

try:
    import websockets
    from websockets.server import serve, WebSocketServerProtocol
except ImportError:
    print("Error: websockets library not found")
    print("Install with: poetry install --with evaluations")
    sys.exit(1)


DEBUG = False


def log_debug(message: str):
    """Print debug message if debug mode is enabled."""
    if DEBUG:
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        print(f"[{timestamp}] [DEBUG] {message}")


def log_info(message: str):
    """Print info message."""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {message}")


async def handle_client(websocket: WebSocketServerProtocol, path: str):
    """
    Handle a WebSocket client connection.

    Args:
        websocket: WebSocket connection
        path: Request path
    """
    client_addr = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    log_info(f"Client connected: {client_addr}")
    log_debug(f"Request path: {path}")
    log_debug(f"Request headers: {dict(websocket.request_headers)}")

    messages_received = 0
    messages_echoed = 0
    bytes_received = 0

    try:
        async for message in websocket:
            # Track bytes
            if isinstance(message, bytes):
                bytes_received += len(message)
                log_debug(f"Received binary message: {len(message)} bytes")
            else:
                bytes_received += len(message.encode('utf-8'))
                log_debug(f"Received text message: {len(message)} chars")

            messages_received += 1

            # Try to parse as JSON for logging
            if DEBUG and isinstance(message, str):
                try:
                    msg_json = json.loads(message)
                    log_debug(f"Parsed JSON with keys: {list(msg_json.keys())}")

                    if msg_json.get("kind") == "AudioData":
                        audio_data = msg_json.get("audioData", {})
                        data_len = len(audio_data.get("data", ""))
                        log_debug(f"  AudioData message:")
                        log_debug(f"    participantRawID: {audio_data.get('participantRawID', 'N/A')}")
                        log_debug(f"    timestamp: {audio_data.get('timestamp', 'N/A')}")
                        log_debug(f"    data length: {data_len} chars (base64)")
                        log_debug(f"    silent: {audio_data.get('silent', 'N/A')}")
                except json.JSONDecodeError:
                    log_debug(f"Message is not JSON: {message[:100]}...")
                except Exception as e:
                    log_debug(f"Error parsing message: {e}")

            # Echo the message back
            await websocket.send(message)
            messages_echoed += 1

            # Progress update every 10 messages
            if messages_received % 10 == 0:
                log_info(f"  Progress: {messages_received} messages received, {messages_echoed} echoed")

    except websockets.exceptions.ConnectionClosed as e:
        log_debug(f"Connection closed: code={e.code}, reason={e.reason}")
    except Exception as e:
        log_info(f"Error: {e}")
        if DEBUG:
            import traceback
            traceback.print_exc()
    finally:
        log_info(f"Client disconnected: {client_addr}")
        log_info(f"  Total messages: {messages_received} received, {messages_echoed} echoed")
        log_info(f"  Total bytes: {bytes_received}")


async def run_server(host: str, port: int, debug: bool = False):
    """
    Run the WebSocket echo server.

    Args:
        host: Host to bind to
        port: Port to listen on
        debug: Enable debug logging
    """
    global DEBUG
    DEBUG = debug

    print("="*60)
    print("Azure Communication Service WebSocket Echo Server")
    print("="*60)
    print(f"Listening on ws://{host}:{port}")
    if debug:
        print("Debug mode: ENABLED")
    print("Press Ctrl+C to stop")
    print("="*60)

    try:
        async with serve(handle_client, host, port):
            # Run forever
            await asyncio.Future()
    except OSError as e:
        if e.errno == 48:  # Address already in use
            print(f"\nError: Port {port} is already in use.")
            print(f"Try a different port with: --port <PORT>")
            return 1
        else:
            print(f"\nError: {e}")
            return 1
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
    except Exception as e:
        print(f"\nError: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return 1

    print("Server stopped.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="WebSocket echo server for Azure Communication Service"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host to bind to (default: localhost, use 0.0.0.0 for all interfaces)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8083,
        help="Port to listen on (default: 8083)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging"
    )

    args = parser.parse_args()

    return asyncio.run(run_server(host=args.host, port=args.port, debug=args.debug))


if __name__ == "__main__":
    sys.exit(main())
