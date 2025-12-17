"""Generate audio files for patient_correction_barge_in test scenario using gTTS.

This script uses Google Text-to-Speech to synthesize Spanish audio files
for testing barge-in functionality.

Requirements:
    - gtts package (pip install gtts)
    - pydub package (pip install pydub) - for format conversion

Usage:
    python production/tests/audio_generation/generate_barge_in_audio_gtts.py
"""
import sys
from pathlib import Path

try:
    from gtts import gTTS
except ImportError:
    print("❌ Error: gTTS not installed")
    print("Install with: pip install gtts")
    sys.exit(1)

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    print("⚠️  Warning: pydub not installed - audio will be saved as MP3")
    print("For WAV conversion, install: pip install pydub")
    print("Also requires ffmpeg: brew install ffmpeg (macOS) or apt-get install ffmpeg (Linux)")
    PYDUB_AVAILABLE = False


def synthesize_to_file(text: str, output_path: Path, lang: str = "es", tld: str = "es") -> bool:
    """Synthesize text to audio file using gTTS.

    Args:
        text: Text to synthesize
        output_path: Path where audio file will be saved
        lang: Language code (default: "es" for Spanish)
        tld: Top-level domain for accent (default: "es" for Spain Spanish)

    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"🎙️  Synthesizing: {text[:60]}...")

        # Create gTTS object
        tts = gTTS(text=text, lang=lang, tld=tld, slow=False)

        # If pydub is available, convert to WAV with proper format
        if PYDUB_AVAILABLE and output_path.suffix.lower() == ".wav":
            # Save to temporary MP3 first
            temp_mp3 = output_path.with_suffix(".temp.mp3")
            tts.save(str(temp_mp3))

            # Load MP3 and convert to 16kHz mono WAV
            audio = AudioSegment.from_mp3(str(temp_mp3))
            audio = audio.set_frame_rate(16000)  # 16kHz sample rate
            audio = audio.set_channels(1)  # Mono
            audio = audio.set_sample_width(2)  # 16-bit

            # Export as WAV
            audio.export(str(output_path), format="wav")

            # Clean up temp file
            temp_mp3.unlink()

            print(f"✅ Success! Audio saved to: {output_path}")
            print(f"   Duration: ~{len(audio) / 1000:.1f} seconds")
        else:
            # Save directly as MP3
            if output_path.suffix.lower() == ".wav" and not PYDUB_AVAILABLE:
                print("⚠️  Warning: Saving as MP3 instead of WAV (pydub not available)")
                output_path = output_path.with_suffix(".mp3")

            tts.save(str(output_path))
            print(f"✅ Success! Audio saved to: {output_path}")

        return True

    except Exception as e:
        print(f"❌ Error synthesizing audio: {e}")
        return False


def main():
    """Generate both audio files for barge-in test scenario."""
    print("="*80)
    print("Generating Audio Files for Barge-In Test Scenario (gTTS)")
    print("="*80)
    print()

    # Define output directory
    script_dir = Path(__file__).parent
    audios_dir = script_dir.parent / "audios"
    audios_dir.mkdir(exist_ok=True)

    # Define audio files and their content
    audio_files = [
        {
            "filename": "patient_correction_001.wav",
            "text": "Buenos días doctor. Vengo porque llevo tres días con un dolor de cabeza constante. El dolor es moderado, está en la parte frontal, y empeora cuando me muevo rápido o me agacho.",
            "description": "Initial patient statement (7-8 seconds)"
        },
        {
            "filename": "patient_correction_002.wav",
            "text": "Perdón, me equivoqué. No es moderado, es bastante fuerte. Y también tengo náuseas y algo de sensibilidad a la luz desde esta mañana.",
            "description": "Patient correction (6-7 seconds)"
        }
    ]

    # Spanish language settings
    lang = "es"  # Spanish
    tld = "es"   # Spain accent
    print(f"🗣️  Language: Spanish (es-ES)")
    print(f"📂 Output directory: {audios_dir}")
    print()

    # Generate each audio file
    success_count = 0
    for audio_info in audio_files:
        output_path = audios_dir / audio_info["filename"]

        print(f"[{audio_files.index(audio_info) + 1}/{len(audio_files)}] {audio_info['description']}")

        success = synthesize_to_file(
            text=audio_info["text"],
            output_path=output_path,
            lang=lang,
            tld=tld
        )

        if success:
            success_count += 1

        print()

    # Summary
    print("="*80)
    if success_count == len(audio_files):
        print(f"✅ Success! Generated {success_count}/{len(audio_files)} audio files")
        print()
        print("Next steps:")
        print("1. Verify audio files in:", audios_dir)
        print("2. Run the test:")
        print("   poetry run prod run-test production/tests/scenarios/patient_correction_barge_in.yaml")
    else:
        print(f"⚠️  Warning: Only {success_count}/{len(audio_files)} files generated successfully")
        print("Please check error messages above")
    print("="*80)


if __name__ == "__main__":
    main()
