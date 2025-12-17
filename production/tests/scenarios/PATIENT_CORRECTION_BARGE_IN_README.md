# Patient Correction Barge-In Test Scenario

## Overview
This test scenario validates how the translation system handles **barge-in** situations where a patient interrupts their own translation to correct or clarify what they just said.

## Test Scenario: `patient_correction_barge_in.yaml`

### Scenario Flow
1. **Initial Statement (0ms)**: Patient provides detailed description of symptoms
   - Patient says: "Buenos días doctor. Vengo porque llevo tres días con un dolor de cabeza constante. El dolor es moderado, está en la parte frontal, y empeora cuando me muevo rápido o me agacho."
   - Expected translation: "Good morning doctor. I'm here because I've had a constant headache for three days. The pain is moderate, it's in the frontal area, and it gets worse when I move quickly or bend down."
   - **Actual audio duration: ~14 seconds** (gTTS synthesis)

2. **Brief Pause (~2 seconds)**: Translation continues playing

3. **Correction with Barge-In (16000ms)**: Patient interrupts during translation playback
   - Patient says: "Perdón, me equivoqué. No es moderado, es bastante fuerte. Y también tengo náuseas y algo de sensibilidad a la luz desde esta mañana."
   - Expected translation: "Sorry, I was wrong. It's not moderate, it's quite severe. And I also have nausea and some light sensitivity since this morning."
   - **Critical**: This starts at 16000ms (16 seconds), interrupting the translation of the first statement
   - **Actual audio duration: ~11 seconds** (gTTS synthesis)

### Barge-In Timing
The key to this test is the timing (with gTTS-generated audio):
- First audio completes at ~14000ms (14 seconds)
- Translation starts streaming shortly after source audio begins
- Translation playback typically lags by 1-3 seconds and continues after source ends
- Second audio starts at **16000ms (16 seconds)**, interrupting the ongoing translation
- This creates a ~2 second gap between audio end and correction, during which translation is playing

**Timing Adjustment Options:**
You can adjust `start_at_ms` in the YAML to test different barge-in scenarios:
- **10000ms**: Interrupt while first audio is still playing (mid-sentence barge-in)
- **14000ms**: Interrupt right as first audio ends
- **16000ms** (current): Interrupt during translation tail with brief pause
- **18000ms+**: Interrupt well into translation playback only

This tests whether the system:
- Stops the previous translation playback
- Clears the translation buffer
- Starts processing the new (correcting) audio
- Delivers the corrected translation without confusion

## Required Audio Files

You need to create two audio files in the `production/tests/audios/` directory:

### 1. `patient_correction_001.wav` ✅ Generated
- **Content (Spanish)**: "Buenos días doctor. Vengo porque llevo tres días con un dolor de cabeza constante. El dolor es moderado, está en la parte frontal, y empeora cuando me muevo rápido o me agacho."
- **Translation**: "Good morning doctor. I'm here because I've had a constant headache for three days. The pain is moderate, it's in the frontal area, and it gets worse when I move quickly or bend down."
- **Actual Duration**: ~14 seconds (gTTS synthesis)
- **Format**: 16-bit PCM, mono, 16kHz WAV
- **Voice**: Google Text-to-Speech Spanish (es-ES)
- **Tone**: Conversational, describing symptoms

### 2. `patient_correction_002.wav` ✅ Generated
- **Content (Spanish)**: "Perdón, me equivoqué. No es moderado, es bastante fuerte. Y también tengo náuseas y algo de sensibilidad a la luz desde esta mañana."
- **Translation**: "Sorry, I was wrong. It's not moderate, it's quite severe. And I also have nausea and some light sensitivity since this morning."
- **Actual Duration**: ~11 seconds (gTTS synthesis)
- **Format**: 16-bit PCM, mono, 16kHz WAV
- **Voice**: Google Text-to-Speech Spanish (es-ES)
- **Tone**: Apologetic/correcting at the beginning, then describing symptoms

**Note**: Audio files have been generated using the `generate_barge_in_audio_gtts.py` script.

## Generating Audio Files

You can generate these audio files using:

### Option 1: Azure TTS (Recommended for consistency)
```bash
# See production/tests/audio_generation/generate_test_scenarios.py for examples
# Use Spanish neural voices like es-ES-ElviraNeural or es-MX-DaliaNeural
```

### Option 2: Google Colab Script
See `production/tests/audio_generation/google_colab_script.ipynb` for TTS generation

### Option 3: Manual Recording
- Record using Audacity or similar tool
- Export as WAV: 16-bit PCM, mono, 16kHz
- Ensure clear audio with minimal background noise

## Audio File Specifications
All audio files must meet these requirements:
- **Format**: WAV (PCM)
- **Sample Rate**: 16kHz
- **Bit Depth**: 16-bit
- **Channels**: Mono (1 channel)
- **Codec**: Uncompressed PCM

## Validation Checklist

After creating the audio files, verify:
- [ ] Both WAV files exist in `production/tests/audios/`
- [ ] Files are named exactly: `patient_correction_001.wav` and `patient_correction_002.wav`
- [ ] Audio format matches specifications (use `file` or `soxi` command)
- [ ] Spanish text matches the `source_text` in the YAML
- [ ] Audio durations are appropriate for realistic speech
- [ ] Voice quality is clear and natural

## Running the Test

Once audio files are ready:

```bash
# Single test execution
poetry run prod run-test production/tests/scenarios/patient_correction_barge_in.yaml

# Check results
ls production_results/patient_correction_barge_in/
```

## Expected Behavior

The system should:
1. ✅ Process the first patient statement
2. ✅ Begin translating "I have a headache"
3. ✅ **Detect the barge-in** when the second audio starts
4. ✅ **Stop or suppress the first translation**
5. ✅ Process the correction statement
6. ✅ Deliver the corrected translation: "Sorry, I was wrong. I have a very severe headache..."

## Metrics to Monitor

Key metrics for this test:
- **Sequence validation**: Were both turns captured in correct order?
- **WER**: Word Error Rate for both translations
- **Completeness**: Was all information from the correction preserved?
- **Technical terms**: Medical terms (headache, nausea, dizziness) correctly translated?
- **Latency**: Time from barge-in detection to new translation start

## Potential Issues to Test For

This scenario helps identify:
- **Translation mixing**: Does the correction translation mix with the first?
- **Buffer clearing**: Is the first translation properly cleared?
- **Audio overlap**: Can the system handle overlapping source audio?
- **Context loss**: Does the correction maintain proper context?
- **Latency spikes**: Does barge-in cause processing delays?

## Next Steps

1. Generate the required audio files using one of the methods above
2. Validate audio file format and content
3. Run the test scenario
4. Review results in `production_results/patient_correction_barge_in/`
5. Check transcript accuracy and barge-in handling
6. Adjust timing in YAML if needed based on actual translation latency