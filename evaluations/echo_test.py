#!/usr/bin/env python3
"""
Echo test server that receives AudioData messages and echoes them back.

This server is useful for testing the run_evaluations.py script without
needing a real translation service.

Usage:
    python echo_test.py
    python echo_test.py --host 0.0.0.0 --port 9000
    python echo_test.py --debug  # Enable verbose debugging
    poetry run echo-test
    poetry run echo-test --port 9000 --debug
"""

import argparse
import json
import socket
import sys
from datetime import datetime, timezone
from typing import Optional


DEBUG = False


def log_debug(message: str):
    """Print debug message if debug mode is enabled."""
    if DEBUG:
        print(f"[DEBUG] {message}")


def parse_audio_data_message(line: str) -> Optional[dict]:
    """
    Parse a JSON AudioData message.

    Args:
        line: JSON string containing AudioData message

    Returns:
        Parsed message dictionary or None if invalid
    """
    try:
        message = json.loads(line)

        log_debug(f"Parsed JSON message with keys: {list(message.keys())}")

        if message.get("kind") == "AudioData":
            log_debug(f"AudioData message found")
            if "audioData" in message:
                audio_data = message["audioData"]
                data_len = len(audio_data.get("data", "")) if "data" in audio_data else 0
                log_debug(f"  participantRawID: {audio_data.get('participantRawID', 'N/A')}")
                log_debug(f"  timestamp: {audio_data.get('timestamp', 'N/A')}")
                log_debug(f"  data length: {data_len} chars")
                log_debug(f"  silent: {audio_data.get('silent', 'N/A')}")
            return message
        else:
            log_debug(f"Message kind is '{message.get('kind')}', not 'AudioData'")
        return None
    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        log_debug(f"Raw line (first 200 chars): {line[:200]}")
        return None


def create_echo_response(original_message: dict) -> dict:
    """
    Create an echo response message based on the original.

    Args:
        original_message: Original AudioData message

    Returns:
        Echo response message (same structure, updated timestamp)
    """
    # Create a copy with updated timestamp
    echo_message = {
        "kind": "AudioData",
        "audioData": {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            "participantRawID": original_message["audioData"]["participantRawID"],
            "data": original_message["audioData"]["data"],
            "silent": original_message["audioData"]["silent"]
        }
    }
    return echo_message


def handle_client(client_socket: socket.socket, client_address: tuple, debug: bool = False, raw_echo: bool = False):
    """
    Handle a single client connection.

    Args:
        client_socket: Connected client socket
        client_address: Client address tuple (host, port)
        debug: Enable debug logging
        raw_echo: Echo messages as-is without parsing
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Client connected: {client_address[0]}:{client_address[1]}")
    if raw_echo:
        print("  Mode: RAW ECHO (messages echoed as-is)")

    chunks_received = 0
    chunks_echoed = 0
    buffer = b""
    bytes_received = 0
    messages_attempted = 0

    try:
        while True:
            # Receive data from client
            data = client_socket.recv(4096)

            if not data:
                # Client closed connection
                log_debug("No data received, client closed connection")
                break

            bytes_received += len(data)
            buffer += data

            log_debug(f"Received {len(data)} bytes, buffer size: {len(buffer)} bytes")

            # Process complete messages (delimited by newline)
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)

                if not line:
                    log_debug("Empty line, skipping")
                    continue

                messages_attempted += 1
                log_debug(f"Processing message #{messages_attempted}, length: {len(line)} bytes")

                # RAW ECHO MODE: Echo back exactly as received
                if raw_echo:
                    chunks_received += 1
                    client_socket.sendall(line + b'\n')
                    chunks_echoed += 1

                    # Print progress every 10 chunks
                    if chunks_received % 10 == 0:
                        print(f"  Echoed: {chunks_received} messages")

                    # In debug mode, show what we're echoing
                    if debug:
                        try:
                            line_str = line.decode('utf-8')
                            log_debug(f"Echoed raw message: {line_str[:200]}...")
                        except:
                            log_debug(f"Echoed raw bytes: {line[:100]}...")
                    continue

                # PARSED MODE: Try to parse and validate
                try:
                    line_str = line.decode('utf-8')
                except UnicodeDecodeError as e:
                    log_debug(f"Unicode decode error: {e}")
                    log_debug(f"Raw bytes (first 100): {line[:100]}")
                    continue

                # Parse AudioData message
                message = parse_audio_data_message(line_str)

                if message:
                    chunks_received += 1

                    # Echo back the audio data
                    echo_message = create_echo_response(message)
                    echo_json = json.dumps(echo_message)
                    client_socket.sendall(echo_json.encode('utf-8') + b'\n')

                    chunks_echoed += 1

                    # Print progress every 10 chunks
                    if chunks_received % 10 == 0:
                        print(f"  Received: {chunks_received} chunks, Echoed: {chunks_echoed} chunks")
                else:
                    log_debug(f"Message was not valid AudioData")
                    if not debug:
                        # Show first message that failed parsing
                        if messages_attempted == 1:
                            print(f"  ⚠ First message was not AudioData. Use --debug for details.")
                            print(f"  Message preview: {line_str[:200]}...")

    except ConnectionResetError:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Client connection reset: {client_address[0]}:{client_address[1]}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error handling client {client_address[0]}:{client_address[1]}: {e}")
        if debug:
            import traceback
            traceback.print_exc()
    finally:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Client disconnected: {client_address[0]}:{client_address[1]}")
        print(f"  Total bytes received: {bytes_received}")
        print(f"  Messages attempted: {messages_attempted}")
        print(f"  AudioData chunks received: {chunks_received}")
        print(f"  AudioData chunks echoed: {chunks_echoed}")
        if chunks_received == 0 and messages_attempted > 0:
            print(f"  ⚠ WARNING: Received {messages_attempted} messages but 0 were valid AudioData")
            print(f"  Use --debug flag to see what messages were received")
        client_socket.close()


def run_echo_server(host: str = "localhost", port: int = 8080, debug: bool = False, raw_echo: bool = False):
    """
    Run the echo server.

    Args:
        host: Host to bind to
        port: Port to listen on
        debug: Enable debug logging
        raw_echo: Echo messages as-is without parsing
    """
    global DEBUG
    DEBUG = debug

    # Create TCP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((host, port))
        server_socket.listen(5)

        print("="*60)
        print("AudioData Echo Test Server")
        print("="*60)
        print(f"Listening on {host}:{port}")
        if raw_echo:
            print("Mode: RAW ECHO (no parsing)")
        if debug:
            print("Debug mode: ENABLED")
        print("Press Ctrl+C to stop")
        print("="*60)

        while True:
            # Accept client connection
            client_socket, client_address = server_socket.accept()

            # Handle client (blocking - one client at a time)
            handle_client(client_socket, client_address, debug, raw_echo)

    except KeyboardInterrupt:
        print("\n\nShutting down server...")
    except OSError as e:
        if e.errno == 48:  # Address already in use
            print(f"\nError: Port {port} is already in use.")
            print(f"Try a different port with: --port <PORT>")
            return 1
        else:
            print(f"\nError: {e}")
            return 1
    except Exception as e:
        print(f"\nError: {e}")
        return 1
    finally:
        server_socket.close()
        print("Server stopped.")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Echo test server for AudioData messages"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host to bind to (default: localhost, use 0.0.0.0 for all interfaces)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to listen on (default: 8080)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging"
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Echo messages as-is without parsing (useful for testing with real ACS)"
    )

    args = parser.parse_args()

    return run_echo_server(host=args.host, port=args.port, debug=args.debug, raw_echo=args.raw)


if __name__ == "__main__":
    sys.exit(main())
