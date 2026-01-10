export function createPlayback({ sampleRate, initialBufferMs }) {
  const context = new AudioContext({ sampleRate });
  const streams = new Map();

  return {
    enqueue(sourceKey, pcmBuffer) {
      const samples = new Int16Array(pcmBuffer);
      const buffer = context.createBuffer(1, samples.length, sampleRate);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < samples.length; i += 1) {
        channel[i] = samples[i] / 0x7fff;
      }

      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);

      const state = streams.get(sourceKey) || { nextTime: context.currentTime + initialBufferMs / 1000 };
      const startTime = Math.max(context.currentTime, state.nextTime);
      source.start(startTime);

      state.nextTime = startTime + buffer.duration;
      streams.set(sourceKey, state);
    },
    close() {
      void context.close();
    }
  };
}
