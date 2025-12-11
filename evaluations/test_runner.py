"""Test execution logic for running evaluation test cases."""

import asyncio
import json
import time
from typing import Dict, Any, List

try:
    import websockets
except ImportError:
    websockets = None

from audio_handler import read_wav_chunks, create_audio_data_message, get_wav_format
from models import TestCase, TestResult


async def run_test_case(
    test_case: TestCase,
    websocket,
    chunk_duration_ms: int,
    verbose: bool = False,
) -> TestResult:
    """
    Run a single test case via WebSocket.

    Args:
        test_case: TestCase to run
        websocket: WebSocket connection
        chunk_duration_ms: Chunk duration in ms
        verbose: Print verbose output

    Returns:
        TestResult with execution details
    """
    print(f"\n{'='*60}")
    print(f"Test Case: [{test_case.id}] {test_case.name}")
    print(f"{'='*60}")
    print(f"  Audio file: {test_case.audio_file}")
    print(f"  Expected text: '{test_case.expected_text}'")
    print(f"  Language: {test_case.language}")
    print(f"  Participant ID: {test_case.participant_id}")

    if test_case.metadata:
        print(f"  Metadata: {test_case.metadata}")

    if not test_case.audio_file.exists():
        print(f"  ✗ ERROR: Audio file not found: {test_case.audio_file}")
        return TestResult(
            test_case=test_case,
            success=False,
            chunks_sent=0,
            response_time_ms=0.0,
            azure_responses=[],
            error_details=f"Audio file not found: {test_case.audio_file}"
        )

    azure_responses = []
    chunks_sent = 0
    start_time = time.time()
    text_deltas = []  # Accumulate text deltas
    last_response_time = time.time()  # Track when we last received data
    first_chunk_sent_time = None  # Time when first chunk was sent
    first_delta_received_time = None  # Time when first text delta was received

    # Inspect WAV format so we can send accurate ACS metadata. This ensures the
    # WebSocket server knows the true sample rate/channels and can resample and
    # play back audio at the correct speed instead of assuming a fixed 16 kHz
    # mono format for all inputs.
    wav_sample_rate, wav_channels, wav_bits_per_sample = get_wav_format(test_case.audio_file)
    print(
        f"  Using WAV format for ACS metadata: "
        f"{wav_sample_rate}Hz, {wav_bits_per_sample}-bit, {wav_channels} channel(s)"
    )

    # Start receiving responses in parallel
    async def receive_responses():
        nonlocal last_response_time, first_delta_received_time
        try:
            while True:
                response = await websocket.recv()
                last_response_time = time.time()  # Update on each response

                if verbose:
                    print(f"\n{'='*60}")
                    print("RECEIVED FROM AZURE:")
                    print(f"{'='*60}")

                if isinstance(response, bytes):
                    if verbose:
                        print(f"Binary response: {len(response)} bytes")
                        print(f"First 100 bytes: {response[:100]}")
                    azure_responses.append({"type": "binary", "data": response[:100]})
                else:
                    if verbose:
                        print(f"Raw payload: {response}")

                    # Try to parse JSON
                    try:
                        response_json = json.loads(response)
                        azure_responses.append({"type": "json", "data": response_json})

                        # Accumulate text deltas
                        if response_json.get("type") == "translation.text_delta":
                            delta = response_json.get("delta", "")
                            text_deltas.append(delta)
                            # Capture time of first text delta received
                            if first_delta_received_time is None:
                                first_delta_received_time = time.time()

                        if verbose:
                            print("\nParsed JSON:")
                            print(json.dumps(response_json, indent=2))
                    except json.JSONDecodeError:
                        azure_responses.append({"type": "text", "data": response})

                if verbose:
                    print(f"{'='*60}\n")

        except websockets.exceptions.ConnectionClosed:
            if verbose:
                print("\nConnection closed by server")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if verbose:
                print(f"\nError receiving responses: {e}")

    receive_task = asyncio.create_task(receive_responses())

    try:
        # Send audio chunks
        print("  Sending audio chunks...")
        for chunk in read_wav_chunks(test_case.audio_file, chunk_duration_ms):
            # Create message
            message = create_audio_data_message(
                chunk,
                test_case.participant_id,
                silent=False,
                sample_rate=wav_sample_rate,
                channels=wav_channels,
                bits_per_sample=wav_bits_per_sample,
            )

            # Convert to JSON and send
            message_json = json.dumps(message)
            await websocket.send(message_json)

            # Capture time of first chunk sent
            if first_chunk_sent_time is None:
                first_chunk_sent_time = time.time()

            chunks_sent += 1

            # Print progress every 10 chunks
            if chunks_sent % 10 == 0:
                print(f"    Sent {chunks_sent} chunks...")

            # Small delay to simulate real-time streaming
            await asyncio.sleep(chunk_duration_ms / 1000.0)

        print(f"  ✓ Completed: {chunks_sent} chunks sent")
        print(f"  📊 Received {len(text_deltas)} text deltas so far")

        # Signal end of stream by sending a special message
        # This triggers Voice Live to commit final buffer without closing the WebSocket
        print("  📤 Sending end-of-stream signal...")
        end_of_stream_message = {
            "kind": "EndOfStream",
            "message": "No more audio data will be sent"
        }
        await websocket.send(json.dumps(end_of_stream_message))

        # Wait for final responses with intelligent timeout
        # Monitor if responses are still coming in
        print("  ⏳ Waiting for final responses...")

        max_wait_time = 90.0  # Maximum 90 seconds
        idle_timeout = 20.0    # Stop if no responses for 5 seconds
        poll_interval = 0.5   # Check every 0.5 seconds

        elapsed = 0.0
        while elapsed < max_wait_time:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            # Check if we've been idle (no responses) for too long
            time_since_last_response = time.time() - last_response_time

            # Show progress every 2 seconds
            if int(elapsed * 2) % 4 == 0:  # Every 2 seconds
                print(f"    ⏱ Waiting... {elapsed:.1f}s elapsed, "
                      f"{len(text_deltas)} deltas, "
                      f"last response {time_since_last_response:.1f}s ago")

            if time_since_last_response > idle_timeout:
                print(f"  ✓ No new responses for {idle_timeout}s (received {len(text_deltas)} text deltas)")
                break

        if elapsed >= max_wait_time:
            print(f"  ⚠ Reached maximum wait time ({max_wait_time}s) with {len(text_deltas)} text deltas")

    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return TestResult(
            test_case=test_case,
            success=False,
            chunks_sent=chunks_sent,
            response_time_ms=(time.time() - start_time) * 1000,
            azure_responses=azure_responses,
            error_details=str(e)
        )
    finally:
        # Cancel receive task
        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass

    end_time = time.time()
    response_time_ms = (end_time - start_time) * 1000

    # Calculate latency (time from first chunk sent to first text delta received)
    latency_ms = None
    if first_chunk_sent_time is not None and first_delta_received_time is not None:
        latency_ms = (first_delta_received_time - first_chunk_sent_time) * 1000

    # Extract recognized text and translations from Azure responses
    # Concatenate text deltas to form complete recognized text
    recognized_text = "".join(text_deltas)
    translations = {}

    for response in azure_responses:
        if response["type"] == "json":
            data = response["data"]
            # Extract translations based on Azure response format
            if "translations" in data:
                translations = data["translations"]

    print(f"\n  {'─'*60}")
    print(f"  📊 Test Completion Summary")
    print(f"  {'─'*60}")
    print(f"  Response time: {response_time_ms:.2f}ms")
    if latency_ms is not None:
        print(f"  Latency (first chunk → first delta): {latency_ms:.2f}ms")
    print(f"  Total responses received: {len(azure_responses)}")
    print(f"  Text deltas received: {len(text_deltas)}")
    print(f"  {'─'*60}")

    if recognized_text:
        print(f"  ✓ Recognized text ({len(recognized_text)} chars):")
        print(f"    '{recognized_text}'")
    else:
        print(f"  ⚠ No recognized text received")

    if test_case.expected_text:
        print(f"  📋 Expected text ({len(test_case.expected_text)} chars):")
        print(f"    '{test_case.expected_text}'")

        # Show comparison
        recognized_words = len(recognized_text.split())
        expected_words = len(test_case.expected_text.split())
        print(f"  📈 Coverage: {recognized_words}/{expected_words} words ({recognized_words/expected_words*100:.1f}%)" if expected_words > 0 else "")

    if translations:
        print(f"  🌐 Translations: {list(translations.keys())}")

    print(f"  {'─'*60}\n")

    return TestResult(
        test_case=test_case,
        success=True,
        chunks_sent=chunks_sent,
        response_time_ms=response_time_ms,
        azure_responses=azure_responses,
        recognized_text=recognized_text,
        translations=translations,
        latency_ms=latency_ms
    )
