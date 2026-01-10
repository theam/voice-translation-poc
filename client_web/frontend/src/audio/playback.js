import { pcm16ToFloat32 } from "./pcm16.js";

export class PlaybackQueue {
  constructor() {
    this.context = new AudioContext({ sampleRate: 16000 });
    this.nextTime = this.context.currentTime;
  }

  enqueue(pcmBytes) {
    const floatData = pcm16ToFloat32(pcmBytes.buffer);
    const buffer = this.context.createBuffer(1, floatData.length, this.context.sampleRate);
    buffer.copyToChannel(floatData, 0);

    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);

    if (this.nextTime < this.context.currentTime) {
      this.nextTime = this.context.currentTime;
    }
    source.start(this.nextTime);
    this.nextTime += buffer.duration;
  }

  stop() {
    this.nextTime = this.context.currentTime;
  }
}
