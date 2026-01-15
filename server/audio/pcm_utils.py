from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from .types import AudioFormat

# Reuse your existing types:
# - AudioFormat
# - UnsupportedAudioFormatError


@dataclass
class PcmUtils:
    """
    Small, fast PCM16 utility focused on RMS (silence/energy detection).

    - Uses NumPy (not deprecated like audioop).
    - Stateful via a fixed `src_fmt` (so callers don't keep passing format).
    - Handles mono or stereo PCM16 little-endian.
    """

    src_fmt: AudioFormat

    def __post_init__(self) -> None:
        self._validate_pcm16(self.src_fmt)

    @staticmethod
    def _validate_pcm16(fmt: AudioFormat) -> None:
        if fmt.sample_format != "pcm16":
            raise UnsupportedAudioFormatError(f"Unsupported audio sample format: {fmt.sample_format}")
        if fmt.channels not in (1, 2):
            raise UnsupportedAudioFormatError(f"Unsupported channel count: {fmt.channels}")
        if fmt.sample_rate_hz <= 0:
            raise UnsupportedAudioFormatError(f"Invalid sample rate: {fmt.sample_rate_hz}")

    def rms_pcm16(self, pcm16: bytes) -> float:
        """
        Compute RMS energy of PCM16 (little-endian signed int16).

        For stereo, this computes per-channel RMS and returns the MAX channel RMS.
        (This is usually the most reliable behavior for silence detection: if either
        channel has speech/noise, we treat it as "not silent".)

        Returns:
            RMS as a float in the same numeric scale as int16 samples (0..~32767).
        """
        if not pcm16:
            return 0.0

        frame_bytes = self.src_fmt.bytes_per_frame()
        usable = len(pcm16) - (len(pcm16) % frame_bytes)
        if usable <= 0:
            return 0.0

        # Interpret as little-endian signed 16-bit samples
        samples = np.frombuffer(pcm16[:usable], dtype="<i2")
        if samples.size == 0:
            return 0.0

        ch = self.src_fmt.channels

        if ch == 1:
            # Float64 for stable math; RMS = sqrt(mean(x^2))
            x = samples.astype(np.float64)
            return float(np.sqrt(np.mean(x * x)))

        # Stereo: reshape to (num_frames, 2) and compute per-channel RMS
        frames = samples.reshape(-1, 2).astype(np.float64)
        # mean over frames for each channel -> shape (2,)
        rms_per_ch = np.sqrt(np.mean(frames * frames, axis=0))
        return float(np.max(rms_per_ch))
