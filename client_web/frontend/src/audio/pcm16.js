export function floatToPcm16(floatBuffer) {
  const pcm = new Int16Array(floatBuffer.length);
  for (let i = 0; i < floatBuffer.length; i += 1) {
    let sample = floatBuffer[i];
    if (sample > 1) sample = 1;
    if (sample < -1) sample = -1;
    pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return pcm.buffer;
}
