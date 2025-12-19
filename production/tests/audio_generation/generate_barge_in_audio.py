"""Generate audio files for patient_correction_barge_in test scenario using Azure TTS.

This script uses Azure Cognitive Services Speech SDK to synthesize Spanish audio
files for testing barge-in functionality.

Requirements:
    - SPEECH__SUBSCRIPTION__KEY environment variable
    - SPEECH__SERVICE__REGION environment variable (e.g., eastus)

Usage:
    poetry run python production/tests/audio_generation/generate_barge_in_audio.py
"""
import os
import sys
from pathlib import Path

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    print("❌ Error: Azure Speech SDK not installed")
    print("Install with: poetry add azure-cognitiveservices-speech")
    sys.exit(1)


def synthesize_to_file(text: str, output_path: Path, voice_name: str = "es-ES-ElviraNeural") -> bool:
    """Synthesize text to audio file using Azure TTS.

    Args:
        text: Text to synthesize
        output_path: Path where audio file will be saved
        voice_name: Azure neural voice to use (default: es-ES-ElviraNeural)

    Returns:
        True if successful, False otherwise
    """
    # Get Azure credentials from environment
    subscription_key = os.getenv("SPEECH__SUBSCRIPTION__KEY")
    service_region = os.getenv("SPEECH__SERVICE__REGION")

    if not subscription_key or not service_region:
        print("❌ Error: Azure Speech credentials not found")
        print("Please set environment variables:")
        print("  - SPEECH__SUBSCRIPTION__KEY")
        print("  - SPEECH__SERVICE__REGION")
        return False

    # Configure speech synthesis
    speech_config = speechsdk.SpeechConfig(
        subscription=subscription_key,
        region=service_region
    )

    # Use Spanish neural voice
    speech_config.speech_synthesis_voice_name = voice_name

    # Configure audio output to file
    # Output format: 16-bit PCM, mono, 16kHz (required by test framework)
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
    )

    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_path))

    # Create synthesizer
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=audio_config
    )

    print(f"🎙️  Synthesizing: {text[:60]}...")
    print(f"📁 Output: {output_path}")

    # Synthesize
    result = synthesizer.speak_text_async(text).get()

    # Check result
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"✅ Success! Audio saved to: {output_path}")
        print(f"   Duration: ~{len(result.audio_data) / (16000 * 2):.1f} seconds")
        return True
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation = result.cancellation_details
        print(f"❌ Speech synthesis canceled: {cancellation.reason}")
        if cancellation.reason == speechsdk.CancellationReason.Error:
            print(f"   Error details: {cancellation.error_details}")
        return False
    else:
        print(f"❌ Unexpected result: {result.reason}")
        return False


def main():
    """Generate both audio files for barge-in test scenario."""
    print("="*80)
    print("Generating Audio Files for Barge-In Test Scenario")
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

    # Spanish neural voice for patient (female voice)
    voice_name = "es-ES-ElviraNeural"
    print(f"🗣️  Voice: {voice_name}")
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
            voice_name=voice_name
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
        print("Please check error messages above and verify Azure credentials")
    print("="*80)


if __name__ == "__main__":
    main()
