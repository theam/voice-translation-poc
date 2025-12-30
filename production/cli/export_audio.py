"""Export wire log audio to WAV file."""
from __future__ import annotations

import logging
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from production.wire_log.parser import WireLogParser

logger = logging.getLogger(__name__)


async def export_audio_async(
    wire_log_path: Path,
    output_path: Optional[Path] = None,
) -> None:
    """Export wire log audio to WAV file.

    Extracts all inbound and outbound AudioData from the wire log and merges
    them chronologically into a single WAV file, mixing overlapping audio as
    it would sound in a telephone call.

    Args:
        wire_log_path: Path to wire log JSONL file
        output_path: Output WAV file path (defaults to wire_log_path.wav)
    """
    # Default output path
    if output_path is None:
        output_path = wire_log_path.with_suffix(".wav")

    # Parse wire log
    logger.info(f"Loading wire log: {wire_log_path}")
    parser = WireLogParser()
    all_messages = parser.load(wire_log_path)

    # Filter audio messages (both inbound and outbound)
    audio_messages = [m for m in all_messages if m.kind.lower() == "audiodata" and m.audio_data]

    if not audio_messages:
        logger.error("No audio messages found in wire log")
        raise typer.Exit(code=1)

    logger.info(f"Found {len(audio_messages)} audio frames")

    # Sort by wall_clock_timestamp to get chronological order
    audio_messages.sort(key=lambda m: m.wall_clock_timestamp)

    # Get first wall clock timestamp as time zero
    first_wall_clock = audio_messages[0].wall_clock_timestamp

    # Separate inbound and outbound
    inbound_messages = [m for m in audio_messages if m.direction == "inbound"]
    outbound_messages = [m for m in audio_messages if m.direction == "outbound"]

    print(f"\n📊 Message counts:")
    print(f"   Inbound:  {len(inbound_messages)} frames")
    print(f"   Outbound: {len(outbound_messages)} frames")

    # Assign timeline positions for inbound:
    # Group by participant and create sequential timeline for each
    # This prevents double-counting silence and captures overlapping speech
    inbound_by_participant = {}
    for msg in inbound_messages:
        participant_id = msg.participant_id or "unknown"
        if participant_id not in inbound_by_participant:
            inbound_by_participant[participant_id] = []
        inbound_by_participant[participant_id].append(msg)

    print(f"\n📊 Inbound participants:")

    # Assign positions for each participant's timeline
    for participant_id, messages in inbound_by_participant.items():
        # First message determines start time for this participant
        first_msg_offset = int((messages[0].wall_clock_timestamp - first_wall_clock).total_seconds() * 1000)

        # Subsequent messages are sequential 20ms from that start
        for i, msg in enumerate(messages):
            msg.timeline_position_ms = first_msg_offset + (i * 20)

        duration_ms = len(messages) * 20
        print(f"   {participant_id}: {len(messages)} frames starting at {first_msg_offset}ms (duration: {duration_ms}ms)")

    # For outbound: Group into turns (detect gaps > 100ms), then space 20ms within each turn
    # This removes noise from irregular network timing while preserving turn structure
    outbound_turns = []
    current_turn = []
    TURN_GAP_THRESHOLD_MS = 100

    for i, msg in enumerate(outbound_messages):
        if i == 0:
            current_turn = [msg]
        else:
            prev_msg = outbound_messages[i - 1]
            gap_ms = int((msg.wall_clock_timestamp - prev_msg.wall_clock_timestamp).total_seconds() * 1000)

            if gap_ms > TURN_GAP_THRESHOLD_MS:
                # New turn detected
                outbound_turns.append(current_turn)
                current_turn = [msg]
            else:
                # Same turn
                current_turn.append(msg)

    # Add last turn
    if current_turn:
        outbound_turns.append(current_turn)

    print(f"\n📊 Outbound turn analysis:")
    print(f"   Detected {len(outbound_turns)} turns")

    # Assign positions: first frame of each turn uses wall clock, rest are sequential 20ms
    for turn_idx, turn in enumerate(outbound_turns):
        # First frame position based on wall clock
        first_frame_offset_ms = int((turn[0].wall_clock_timestamp - first_wall_clock).total_seconds() * 1000)

        # Assign positions within turn
        for frame_idx, msg in enumerate(turn):
            msg.timeline_position_ms = first_frame_offset_ms + (frame_idx * 20)

        print(f"      Turn {turn_idx + 1}: {len(turn)} frames starting at {first_frame_offset_ms}ms")

    # Recombine and find max timeline position
    all_messages = inbound_messages + outbound_messages
    max_position = max(m.timeline_position_ms for m in all_messages)
    duration_ms = max_position + 20  # Add last frame duration

    print(f"\n📊 Timeline:")
    print(f"   Duration: {duration_ms}ms ({duration_ms / 1000:.2f}s)")
    print(f"\n   First 10 frames by timeline position:")

    # Sort by timeline position for display
    all_messages.sort(key=lambda m: m.timeline_position_ms)
    # Use all_messages for mixing (already sorted by timeline position)
    audio_messages = all_messages

    # Create audio buffer (16kHz, mono, 16-bit PCM)
    SAMPLE_RATE = 16000
    num_samples = (duration_ms * SAMPLE_RATE) // 1000
    audio_buffer = [0] * num_samples

    # Mix all audio frames into the buffer using timeline positions
    inbound_count = 0
    outbound_count = 0

    for idx, msg in enumerate(audio_messages):
        # Use pre-calculated timeline position
        offset_ms = msg.timeline_position_ms  # type: ignore
        start_sample = (offset_ms * SAMPLE_RATE) // 1000

        # Safety check
        if start_sample < 0:
            logger.warning(f"Message {idx} has negative offset ({offset_ms}ms), skipping")
            continue

        # Decode PCM16 samples (little-endian signed 16-bit)
        num_frame_samples = len(msg.audio_data) // 2

        for i in range(num_frame_samples):
            sample_idx = start_sample + i

            # Skip if beyond buffer
            if sample_idx >= num_samples:
                break

            # Read 16-bit signed sample (little-endian)
            byte_offset = i * 2
            sample = int.from_bytes(
                msg.audio_data[byte_offset : byte_offset + 2],
                byteorder="little",
                signed=True,
            )

            # Mix (add) samples - clamp to prevent overflow
            mixed = audio_buffer[sample_idx] + sample
            audio_buffer[sample_idx] = max(-32768, min(32767, mixed))

        if msg.direction == "inbound":
            inbound_count += 1
        else:
            outbound_count += 1

    # Convert buffer back to bytes
    pcm_data = bytearray()
    for sample in audio_buffer:
        pcm_data.extend(sample.to_bytes(2, byteorder="little", signed=True))

    # Write WAV file
    logger.info(f"Writing WAV file: {output_path}")
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit = 2 bytes
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(bytes(pcm_data))

    duration_s = duration_ms / 1000

    print("✅ Audio exported successfully!")
    print(f"   Output: {output_path}")
    print(f"   Duration: {duration_s:.2f}s ({duration_ms}ms)")
    print(f"   Frames: {len(audio_messages)} ({inbound_count} inbound, {outbound_count} outbound)")
    print(f"   Format: 16kHz, mono, PCM16")


__all__ = ["export_audio_async"]
