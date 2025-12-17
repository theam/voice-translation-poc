"""Build a full-call audio mix for manual verification."""
from __future__ import annotations

from array import array
import contextlib
import io
import wave
from pathlib import Path
from typing import List, Tuple


def _samples_from_ms(start_ms: int, sample_rate: int) -> int:
    return int(round(start_ms * sample_rate / 1000))


class ConversationTape:
    """Accumulates PCM frames with timestamps and renders a mixed WAV payload.

    Audio is mixed in the order it arrives—no synthetic silence is injected—so
    the resulting tape mirrors what a continuous phone line would capture when
    silence frames are streamed during idle periods.
    """

    def __init__(self, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        self._segments: List[Tuple[int, bytes]] = []  # (start_ms, pcm_bytes)

    def add_pcm(self, start_ms: int, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        safe_start = max(0, start_ms)
        self._segments.append((safe_start, pcm_bytes))

    def render(self) -> bytes:
        """Return a mono 16-bit PCM mix of all recorded segments.

        This method mixes audio in bounded chunks to avoid excessive memory
        consumption. For large conversations prefer :meth:`write_wav` so the
        mix is streamed directly to disk.
        """

        buffer = io.BytesIO()
        self.write_wav(Path("/dev/stdout"), buffer_override=buffer)
        return buffer.getvalue()

    def write_wav(self, path: Path, chunk_ms: int = 1000, buffer_override: io.BytesIO | None = None) -> None:
        """Stream a mixed WAV to ``path`` using bounded buffers.

        Args:
            path: Destination file path.
            chunk_ms: Mix window size in milliseconds. Smaller windows reduce
                peak memory at the expense of additional CPU.
            buffer_override: Internal use for tests; when provided, the WAV is
                written to the supplied in-memory buffer instead of the file
                system.
        """

        if not self._segments:
            return

        sample_width = 2
        segments: List[Tuple[int, array]] = []
        min_start_ms = min(start for start, _ in self._segments)
        max_end_ms = max(start + len(pcm) / 2 / self.sample_rate * 1000 for start, pcm in self._segments)

        import logging
        logger = logging.getLogger(__name__)

        logger.info(
            f"🎵 CONVERSATION TAPE: "
            f"total_segments={len(self._segments)}, "
            f"timeline_span={min_start_ms}ms-{int(max_end_ms)}ms, "
            f"duration={int(max_end_ms - min_start_ms)}ms"
        )

        for start_ms, pcm in sorted(self._segments, key=lambda seg: seg[0]):
            samples = array("h")
            samples.frombytes(pcm)
            # Normalize timestamps so the earliest audio begins at t=0. This
            # prevents enormous leading silence if callers pass absolute wall
            # clock timestamps (e.g., ISO-8601 parsed values), which could
            # otherwise expand the WAV header beyond 4 GiB and fail to write.
            normalized_start = _samples_from_ms(start_ms - min_start_ms, self.sample_rate)
            segments.append((normalized_start, samples))

        total_samples = max(start + len(samples) for start, samples in segments)
        total_duration_s = total_samples / self.sample_rate

        logger.info(
            f"🎵 MIXED WAV: "
            f"total_samples={total_samples}, "
            f"duration={total_duration_s:.2f}s, "
            f"sample_rate={self.sample_rate}Hz"
        )
        chunk_samples = max(1, _samples_from_ms(chunk_ms, self.sample_rate))

        wav_io = buffer_override if buffer_override is not None else open(path, "wb")
        with contextlib.ExitStack() as stack:
            if buffer_override is None:
                wav_io = stack.enter_context(wav_io)

            with wave.open(wav_io, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(sample_width)
                wav.setframerate(self.sample_rate)

                for block_start in range(0, total_samples, chunk_samples):
                    block_end = min(total_samples, block_start + chunk_samples)
                    block_len = block_end - block_start
                    accumulator = array("i", [0] * block_len)

                    for seg_start, samples in segments:
                        seg_end = seg_start + len(samples)
                        if seg_end <= block_start or seg_start >= block_end:
                            continue

                        overlap_start = max(block_start, seg_start)
                        overlap_end = min(block_end, seg_end)
                        seg_offset = overlap_start - seg_start
                        acc_offset = overlap_start - block_start
                        overlap_len = overlap_end - overlap_start

                        for idx in range(overlap_len):
                            accumulator[acc_offset + idx] += samples[seg_offset + idx]

                    mixed_block = array("h", [0] * block_len)
                    for idx, value in enumerate(accumulator):
                        if value > 32767:
                            value = 32767
                        elif value < -32768:
                            value = -32768
                        mixed_block[idx] = int(value)

                    wav.writeframes(mixed_block.tobytes())


__all__ = ["ConversationTape"]
