export type CaptureOptions = {
  sampleRate: number;
  frameMs: number;
  onFrame: (frame: ArrayBuffer) => void;
  onLevel?: (level: number) => void;
};

export type CaptureHandle = {
  setMuted: (muted: boolean) => void;
  stop: () => void;
};

export async function startCapture(options: CaptureOptions): Promise<CaptureHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const context = new AudioContext({ sampleRate: options.sampleRate });
  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(4096, 1, 1);
  const gain = context.createGain();
  gain.gain.value = 0;

  let muted = false;
  let buffer = new Float32Array(0);
  const frameSamples = Math.floor((options.sampleRate * options.frameMs) / 1000);

  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0);
    let rms = 0;
    for (let i = 0; i < input.length; i += 1) {
      rms += input[i] * input[i];
    }
    rms = Math.sqrt(rms / input.length);
    options.onLevel?.(rms);

    const combined = new Float32Array(buffer.length + input.length);
    combined.set(buffer);
    combined.set(input, buffer.length);
    buffer = combined;

    while (buffer.length >= frameSamples) {
      const frame = buffer.slice(0, frameSamples);
      buffer = buffer.slice(frameSamples);

      if (!muted) {
        const pcm = new Int16Array(frameSamples);
        for (let i = 0; i < frameSamples; i += 1) {
          let sample = frame[i];
          if (sample > 1) sample = 1;
          if (sample < -1) sample = -1;
          pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
        }
        options.onFrame(pcm.buffer);
      }
    }
  };

  source.connect(processor);
  processor.connect(gain);
  gain.connect(context.destination);

  const stop = () => {
    processor.disconnect();
    source.disconnect();
    gain.disconnect();
    stream.getTracks().forEach((track) => track.stop());
    void context.close();
  };

  return {
    setMuted: (value) => {
      muted = value;
    },
    stop
  };
}
