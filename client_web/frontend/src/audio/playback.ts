export type PlaybackOptions = {
  sampleRate: number;
  initialBufferMs: number;
};

export type PlaybackHandle = {
  enqueue: (sourceKey: string, pcm: ArrayBuffer) => void;
  close: () => void;
};

type StreamState = {
  nextTime: number;
};

export function createPlayback(options: PlaybackOptions): PlaybackHandle {
  const context = new AudioContext({ sampleRate: options.sampleRate });
  const streams = new Map<string, StreamState>();

  const enqueue = (sourceKey: string, pcm: ArrayBuffer) => {
    const samples = new Int16Array(pcm);
    const buffer = context.createBuffer(1, samples.length, options.sampleRate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i += 1) {
      channel[i] = samples[i] / 0x7fff;
    }

    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);

    const stream = streams.get(sourceKey) ?? { nextTime: context.currentTime + options.initialBufferMs / 1000 };
    const startTime = Math.max(context.currentTime, stream.nextTime);
    source.start(startTime);

    stream.nextTime = startTime + buffer.duration;
    streams.set(sourceKey, stream);
  };

  const close = () => {
    void context.close();
  };

  return { enqueue, close };
}
