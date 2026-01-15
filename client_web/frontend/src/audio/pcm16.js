/**
 * PCM16 audio conversion utilities for ACS standard format.
 *
 * ACS uses PCM16 (16-bit signed integer) encoding:
 * - Range: -32768 to 32767
 * - Web Audio API uses Float32: -1.0 to 1.0
 * - These functions convert between the two formats
 */

/**
 * Convert Float32 audio samples to PCM16 (Int16).
 * Used for capture: Float32 [-1.0, 1.0] → Int16 [-32768, 32767]
 */
export function floatTo16BitPCM(float32Array) {
  const output = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i += 1) {
    // Clamp to [-1.0, 1.0] range
    let s = Math.max(-1, Math.min(1, float32Array[i]));
    // Convert: negative uses full -32768, positive uses -32767 (symmetric)
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output;
}

/**
 * Convert PCM16 (Int16) audio samples to Float32.
 * Used for playback: Int16 [-32768, 32767] → Float32 [-1.0, 1.0]
 */
export function pcm16ToFloat32(buffer) {
  const data = new Int16Array(buffer);
  const floats = new Float32Array(data.length);
  for (let i = 0; i < data.length; i += 1) {
    // Divide by 32768 to normalize to [-1.0, 1.0]
    floats[i] = data[i] / 0x8000;
  }
  return floats;
}

/**
 * Encode PCM16 bytes to base64 for transmission.
 * Processes in chunks to avoid call stack size limits.
 */
export function base64FromBytes(bytes) {
  let binary = "";
  const chunkSize = 0x8000; // 32KB chunks
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

/**
 * Decode base64 to PCM16 bytes for playback.
 */
export function bytesFromBase64(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}
