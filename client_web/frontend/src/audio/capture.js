import { base64FromBytes, floatTo16BitPCM } from "./pcm16.js";

/**
 * AudioCapture captures microphone audio and converts it to ACS standard format.
 *
 * Conversion pipeline:
 * 1. Microphone input at hardware rate (typically 48kHz) → Float32Array
 * 2. Resample to 16kHz using linear interpolation
 * 3. Convert Float32 to PCM16 (Int16Array)
 * 4. Base64 encode for transmission
 *
 * Output: 16kHz mono PCM16 (ACS standard format enforced by backend)
 */
export class AudioCapture {
  constructor({ onAudioFrame }) {
    this.onAudioFrame = onAudioFrame;
    this.context = null;
    this.processor = null;
    this.stream = null;
    this.frameSize = 1024;
    this.targetSampleRate = 16000; // ACS standard: 16kHz mono PCM16
    this.targetFrameSamples = 320; // 20ms at 16kHz
    this.resampleBuffer = new Float32Array(0);
  }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    // Use hardware sample rate (Firefox doesn't support custom sample rates)
    this.context = new AudioContext();
    const source = this.context.createMediaStreamSource(this.stream);
    this.processor = this.context.createScriptProcessor(this.frameSize, 1, 1);

    const sourceSampleRate = this.context.sampleRate;
    const resampleRatio = sourceSampleRate / this.targetSampleRate;

    this.processor.onaudioprocess = (event) => {
      // Get mono channel at hardware rate (e.g., 48kHz)
      const input = event.inputBuffer.getChannelData(0);

      // Resample from hardware rate → 16kHz
      const resampled = this.resample(input, resampleRatio);

      this._appendResampled(resampled);
      while (this.resampleBuffer.length >= this.targetFrameSamples) {
        const frame = this.resampleBuffer.subarray(0, this.targetFrameSamples);
        this.resampleBuffer = this.resampleBuffer.subarray(this.targetFrameSamples);

        // Convert Float32 → PCM16 (Int16)
        const pcm = floatTo16BitPCM(frame);
        const bytes = new Uint8Array(pcm.buffer);
        const base64 = base64FromBytes(bytes);

        // Send 16kHz mono PCM16 (ACS standard format)
        this.onAudioFrame({
          data: base64,
          timestamp_ms: Date.now(),
        });
      }
    };
    source.connect(this.processor);
    this.processor.connect(this.context.destination);
  }

  /**
   * Resample audio using linear interpolation.
   * For downsampling (e.g., 48kHz → 16kHz), ratio > 1 (e.g., 3.0)
   * Each output sample maps to ratio * i in input samples (skipping)
   */
  resample(input, ratio) {
    if (ratio === 1.0) {
      return input;
    }

    const outputLength = Math.floor(input.length / ratio);
    const output = new Float32Array(outputLength);

    for (let i = 0; i < outputLength; i++) {
      const sourceIndex = i * ratio;
      const sourceIndexFloor = Math.floor(sourceIndex);
      const sourceIndexCeil = Math.min(sourceIndexFloor + 1, input.length - 1);
      const fraction = sourceIndex - sourceIndexFloor;

      // Linear interpolation between adjacent samples
      output[i] = input[sourceIndexFloor] * (1 - fraction) + input[sourceIndexCeil] * fraction;
    }

    return output;
  }

  _appendResampled(resampled) {
    if (this.resampleBuffer.length === 0) {
      this.resampleBuffer = resampled;
      return;
    }

    const combined = new Float32Array(this.resampleBuffer.length + resampled.length);
    combined.set(this.resampleBuffer);
    combined.set(resampled, this.resampleBuffer.length);
    this.resampleBuffer = combined;
  }

  stop() {
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
    if (this.context) {
      this.context.close();
      this.context = null;
    }
    if (this.stream) {
      for (const track of this.stream.getTracks()) {
        track.stop();
      }
      this.stream = null;
    }
  }
}
