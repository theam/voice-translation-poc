import { pcm16ToFloat32 } from "./pcm16.js";

export class PlaybackQueue {
  constructor() {
    this.context = null;
    this.nextTime = 0;
    this.inputSampleRate = 16000;
  }

  async ensureContext() {
    if (!this.context) {
      // Use hardware sample rate (Firefox compatibility)
      this.context = new AudioContext();
      this.nextTime = this.context.currentTime;
      console.log(`Playback AudioContext created: ${this.context.sampleRate} Hz`);
    }

    // Resume context if suspended (autoplay policy)
    if (this.context.state === "suspended") {
      console.log("Resuming suspended AudioContext...");
      await this.context.resume();
      console.log("AudioContext resumed");
    }
  }

  async enqueue(pcmBytes) {
    await this.ensureContext();

    const floatData = pcm16ToFloat32(pcmBytes.buffer);

    // Resample from 16000 Hz to hardware rate if needed
    const resampleRatio = this.context.sampleRate / this.inputSampleRate;
    const resampledData = this.resample(floatData, resampleRatio);

    const buffer = this.context.createBuffer(1, resampledData.length, this.context.sampleRate);
    buffer.copyToChannel(resampledData, 0);

    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);

    if (this.nextTime < this.context.currentTime) {
      this.nextTime = this.context.currentTime;
    }
    source.start(this.nextTime);
    console.log(`Audio scheduled at ${this.nextTime.toFixed(3)}s, duration ${buffer.duration.toFixed(3)}s`);
    this.nextTime += buffer.duration;
  }

  resample(input, ratio) {
    if (Math.abs(ratio - 1.0) < 0.001) {
      return input;
    }

    const outputLength = Math.floor(input.length * ratio);
    const output = new Float32Array(outputLength);

    for (let i = 0; i < outputLength; i++) {
      const sourceIndex = i / ratio;
      const sourceIndexFloor = Math.floor(sourceIndex);
      const sourceIndexCeil = Math.min(sourceIndexFloor + 1, input.length - 1);
      const fraction = sourceIndex - sourceIndexFloor;

      // Linear interpolation
      output[i] = input[sourceIndexFloor] * (1 - fraction) + input[sourceIndexCeil] * fraction;
    }

    return output;
  }

  stop() {
    if (this.context) {
      this.nextTime = this.context.currentTime;
    }
  }
}
