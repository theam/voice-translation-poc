"""Resample a WAV file to 16 kHz mono PCM."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np


def resample_to_16k(input_path: Path, output_path: Path) -> None:
    with wave.open(str(input_path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        samples = np.frombuffer(frames, dtype=np.int16)
        input_sr = wf.getframerate()

    target_sr = 16000
    if input_sr != target_sr:
        duration = len(samples) / input_sr
        new_len = int(duration * target_sr)
        resampled = np.interp(
            np.linspace(0, len(samples), new_len, endpoint=False),
            np.arange(len(samples)),
            samples,
        ).astype(np.int16)
    else:
        resampled = samples

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(target_sr)
        wf.writeframes(resampled.tobytes())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resample WAV to 16 kHz mono.")
    parser.add_argument("input", type=Path, help="Path to the source WAV file.")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="Optional path for the resampled WAV (defaults to <name>-16k.wav).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output or args.input.with_name(f"{args.input.stem}-16k.wav")
    resample_to_16k(args.input, output_path)
    print(f"Saved {output_path}")


if __name__ == "__main__":
    main()

