#!/usr/bin/env python3
"""Test client to verify real-time translation streaming."""

import asyncio
import json
import sys
import websockets

async def test_streaming():
    """Connect to the WebSocket server and display streaming events."""
    uri = "ws://localhost:8765"
    
    print(f"Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✓ Connected to server")
            print("Listening for translation events...")
            print("-" * 60)
            
            async for message in websocket:
                try:
                    event = json.loads(message)
                    event_type = event.get("type", "unknown")
                    
                    if event_type == "translation.started":
                        print("\n🎤 Translation started")
                    
                    elif event_type == "translation.text_delta":
                        delta = event.get("delta", "")
                        print(f"📝 Text: {delta}", end="", flush=True)
                    
                    elif event_type == "translation.audio_delta":
                        audio_len = len(event.get("audio", ""))
                        print(f"\n🔊 Audio chunk: {audio_len} bytes (base64)")
                    
                    elif event_type == "status":
                        status = event.get("status", "")
                        print(f"\n📊 Status: {status}")
                    
                    elif event_type == "processed":
                        print(f"\n✅ Final result:")
                        print(f"   Recognized: {event.get('recognized_text')}")
                        print(f"   Translations: {event.get('translations')}")
                        print(f"   Success: {event.get('success')}")
                    
                    else:
                        # Display other events
                        print(f"\n📨 {event_type}: {json.dumps(event, indent=2)}")
                
                except json.JSONDecodeError:
                    print(f"⚠️  Invalid JSON: {message}")
                except KeyboardInterrupt:
                    print("\n\n👋 Disconnecting...")
                    break
    
    except ConnectionRefusedError:
        print("❌ Connection refused. Is the server running?")
        print("   Start with: poetry run speech-poc serve --host localhost --port 8765")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(test_streaming())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
