import { base64FromBytes, floatTo16BitPCM } from "./pcm16.js";

export class AudioCapture {
  constructor({ onAudioFrame, onMetadata }) {
    this.onAudioFrame = onAudioFrame;
    this.onMetadata = onMetadata;
    this.context = null;
    this.processor = null;
    this.stream = null;
    this.frameSize = 4096;
    this.targetSampleRate = 16000;
    this.resampleBuffer = [];
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
      const input = event.inputBuffer.getChannelData(0);

      // Resample from hardware rate to 16000 Hz
      const resampled = this.resample(input, resampleRatio);

      const pcm = floatTo16BitPCM(resampled);
      const bytes = new Uint8Array(pcm.buffer);
      const base64 = base64FromBytes(bytes);
      this.onAudioFrame({
        data: base64,
        timestamp_ms: Date.now(),
      });
    };
    source.connect(this.processor);
    this.processor.connect(this.context.destination);

    this.onMetadata({
      sample_rate: this.targetSampleRate,
      channels: 1,
      frame_bytes: Math.floor(this.frameSize / resampleRatio) * 2,
    });
  }

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

      // Linear interpolation
      output[i] = input[sourceIndexFloor] * (1 - fraction) + input[sourceIndexCeil] * fraction;
    }

    return output;
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
