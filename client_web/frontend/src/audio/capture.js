import { floatToPcm16 } from "./pcm16";

export async function startCapture({ sampleRate, frameMs, onFrame, onLevel }) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const context = new AudioContext({ sampleRate });
  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(4096, 1, 1);
  const gain = context.createGain();
  gain.gain.value = 0;

  let muted = false;
  let buffer = new Float32Array(0);
  const frameSamples = Math.floor((sampleRate * frameMs) / 1000);

  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0);
    let rms = 0;
    for (let i = 0; i < input.length; i += 1) {
      rms += input[i] * input[i];
    }
    onLevel?.(Math.sqrt(rms / input.length));

    const combined = new Float32Array(buffer.length + input.length);
    combined.set(buffer);
    combined.set(input, buffer.length);
    buffer = combined;

    while (buffer.length >= frameSamples) {
      const frame = buffer.slice(0, frameSamples);
      buffer = buffer.slice(frameSamples);

      if (!muted) {
        onFrame(floatToPcm16(frame));
      }
    }
  };

  source.connect(processor);
  processor.connect(gain);
  gain.connect(context.destination);

  return {
    setMuted(nextMuted) {
      muted = nextMuted;
    },
    stop() {
      processor.disconnect();
      source.disconnect();
      gain.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      void context.close();
    }
  };
}
