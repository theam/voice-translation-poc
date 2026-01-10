import { base64FromBytes, floatTo16BitPCM } from "./pcm16.js";

export class AudioCapture {
  constructor({ onAudioFrame, onMetadata }) {
    this.onAudioFrame = onAudioFrame;
    this.onMetadata = onMetadata;
    this.context = null;
    this.processor = null;
    this.stream = null;
    this.frameSize = 4096;
  }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.context = new AudioContext({ sampleRate: 16000 });
    const source = this.context.createMediaStreamSource(this.stream);
    this.processor = this.context.createScriptProcessor(this.frameSize, 1, 1);
    this.processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const pcm = floatTo16BitPCM(input);
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
      sample_rate: this.context.sampleRate,
      channels: 1,
      frame_bytes: this.frameSize * 2,
    });
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
