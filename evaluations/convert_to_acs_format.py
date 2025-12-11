#!/usr/bin/env python3
"""
Convert audio files to Azure Communication Service format (16 kHz, 16-bit, mono PCM).

Usage:
    python convert_to_acs_format.py input.wav output.wav
    python convert_to_acs_format.py --folder input_folder/ --output-folder acs_format/
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List


ACS_SAMPLE_RATE = 16000
ACS_BITS_PER_SAMPLE = 16
ACS_CHANNELS = 1


def convert_with_ffmpeg(input_path: Path, output_path: Path) -> bool:
    """
    Convert audio file to ACS format using ffmpeg.

    Args:
        input_path: Input audio file
        output_path: Output WAV file

    Returns:
        True if successful, False otherwise
    """
    try:
        # Create output directory if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # ffmpeg command for ACS format
        cmd = [
            "ffmpeg",
            "-i", str(input_path),
            "-ar", str(ACS_SAMPLE_RATE),      # Sample rate: 16 kHz
            "-ac", str(ACS_CHANNELS),         # Channels: mono
            "-sample_fmt", "s16",             # Sample format: 16-bit signed
            "-y",                             # Overwrite output
            str(output_path)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0:
            print(f"✓ Converted: {input_path.name} -> {output_path.name}")
            return True
        else:
            print(f"✗ Failed to convert {input_path.name}:")
            print(f"  {result.stderr}")
            return False

    except FileNotFoundError:
        print("Error: ffmpeg not found. Install with: brew install ffmpeg")
        return False
    except Exception as e:
        print(f"Error converting {input_path.name}: {e}")
        return False


def convert_file(input_path: Path, output_path: Path) -> bool:
    """Convert a single audio file."""
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return False

    print(f"\nConverting: {input_path}")
    print(f"Output: {output_path}")
    return convert_with_ffmpeg(input_path, output_path)


def convert_folder(input_folder: Path, output_folder: Path) -> int:
    """
    Convert all audio files in a folder.

    Returns:
        Number of files successfully converted
    """
    if not input_folder.exists() or not input_folder.is_dir():
        print(f"Error: Input folder not found: {input_folder}")
        return 0

    # Find all audio files
    audio_extensions = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
    audio_files = [
        f for f in input_folder.rglob("*")
        if f.is_file() and f.suffix.lower() in audio_extensions
    ]

    if not audio_files:
        print(f"No audio files found in {input_folder}")
        return 0

    print(f"Found {len(audio_files)} audio file(s) to convert")

    success_count = 0
    for audio_file in audio_files:
        # Preserve directory structure
        relative_path = audio_file.relative_to(input_folder)
        output_path = output_folder / relative_path.with_suffix('.wav')

        if convert_with_ffmpeg(audio_file, output_path):
            success_count += 1

    return success_count


def main():
    parser = argparse.ArgumentParser(
        description="Convert audio files to Azure Communication Service format"
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        help="Input audio file (or use --folder)"
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="Output WAV file (or use --output-folder)"
    )
    parser.add_argument(
        "--folder",
        type=Path,
        help="Input folder containing audio files"
    )
    parser.add_argument(
        "--output-folder",
        type=Path,
        help="Output folder for converted files"
    )

    args = parser.parse_args()

    print("="*60)
    print("Azure Communication Service Audio Converter")
    print("="*60)
    print(f"Target format: {ACS_SAMPLE_RATE} Hz, {ACS_BITS_PER_SAMPLE}-bit, {ACS_CHANNELS} channel (mono)")
    print("="*60)

    # Folder mode
    if args.folder:
        if not args.output_folder:
            parser.error("--output-folder is required when using --folder")

        success_count = convert_folder(args.folder, args.output_folder)

        print("\n" + "="*60)
        print(f"Conversion complete: {success_count} file(s) converted")
        print("="*60)

        return 0 if success_count > 0 else 1

    # Single file mode
    if not args.input or not args.output:
        parser.error("Either provide input/output files or use --folder/--output-folder")

    success = convert_file(args.input, args.output)

    print("\n" + "="*60)
    if success:
        print("Conversion complete!")
    else:
        print("Conversion failed!")
    print("="*60)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
