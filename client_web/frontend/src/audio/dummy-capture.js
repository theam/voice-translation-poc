import { base64FromBytes } from "./pcm16.js";

/**
 * DummyCapture simulates microphone input by loading and sending a WAV file.
 *
 * Controlled assumptions (kept):
 * - WAV is guaranteed: 44-byte header, 16kHz mono PCM16, data starts at byte 44
 *
 * Improvements:
 * - Self-correcting pacing (performance.now) instead of setInterval (reduces jitter/bursts)
 * - Prevent burst catch-up: if late, skip forward instead of sending many chunks at once
 * - Clear gap timeout on stop
 */
export class DummyCapture {
  constructor({ onAudioFrame, wavFilePath }) {
    this.onAudioFrame = onAudioFrame;
    this.wavFilePath = wavFilePath;

    this.audioData = null; // Int16Array
    this.position = 0;

    // 16kHz mono PCM16
    this.sampleRate = 16000;

    // 1024 samples @ 16kHz ≈ 64ms
    this.chunkSize = 1024;
    this.chunkMs = (this.chunkSize / this.sampleRate) * 1000; // ~64ms

    this.gapMs = 10000;
    this.isInGap = false;

    // Scheduling
    this._running = false;
    this._timer = null;
    this._gapTimer = null;

    // Next planned send time on performance.now() clock
    this._nextTickAt = 0;

    // If we fall behind, do NOT send a huge burst; skip forward.
    this._maxCatchupChunks = 2;
  }

  async start() {
    console.log(`[DummyCapture] Loading WAV file from ${this.wavFilePath}...`);

    const response = await fetch(this.wavFilePath);
    if (!response.ok) {
      throw new Error(`Failed to load WAV file: ${response.status} ${response.statusText}`);
    }

    const arrayBuffer = await response.arrayBuffer();

    // Controlled environment: 44-byte header, PCM16 data starts at offset 44
    const header = new DataView(arrayBuffer, 0, 44);
    const sampleRate = header.getUint32(24, true);
    const numChannels = header.getUint16(22, true);
    const bitsPerSample = header.getUint16(34, true);

    console.log(`[DummyCapture] WAV info: ${sampleRate}Hz, ${numChannels} channel(s), ${bitsPerSample}-bit`);

    if (bitsPerSample !== 16) throw new Error(`Invalid WAV: expected 16-bit, got ${bitsPerSample}`);
    if (numChannels !== 1) console.warn(`[DummyCapture] Expected mono, got ${numChannels}.`);
    if (sampleRate !== 16000) console.warn(`[DummyCapture] Expected 16kHz, got ${sampleRate}Hz.`);

    this.audioData = new Int16Array(arrayBuffer.slice(44));
    const durationSeconds = this.audioData.length / sampleRate;

    console.log(`[DummyCapture] Loaded ${this.audioData.length} samples (${durationSeconds.toFixed(1)}s)`);

    this.position = 0;
    this.isInGap = false;

    this._running = true;
    this._nextTickAt = performance.now(); // anchor pacing to now
    this._scheduleTick(0);

    console.log("[DummyCapture] Started sending audio chunks");
  }

  stop() {
    console.log("[DummyCapture] Stopping");

    this._running = false;

    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
    if (this._gapTimer) {
      clearTimeout(this._gapTimer);
      this._gapTimer = null;
    }

    this.audioData = null;
    this.position = 0;
    this.isInGap = false;
  }

  _scheduleTick(delayMs) {
    if (!this._running) return;
    this._timer = setTimeout(() => this._tick(), delayMs);
  }

  _tick() {
    if (!this._running) return;

    const now = performance.now();

    if (this.isInGap) {
      this._scheduleTick(50);
      return;
    }

    // Compute how many chunks are due; clamp to avoid burst sending
    let chunksDue = Math.floor((now - this._nextTickAt) / this.chunkMs) + 1;
    if (chunksDue < 1) chunksDue = 1;

    if (chunksDue > this._maxCatchupChunks) {
      // Late: skip forward instead of bursting
      const skipChunks = chunksDue - this._maxCatchupChunks;
      this.position += skipChunks * this.chunkSize;
      chunksDue = this._maxCatchupChunks;
    }

    for (let i = 0; i < chunksDue; i++) {
      this._sendOneChunk();
      this._nextTickAt += this.chunkMs;
      if (this.isInGap) break;
    }

    const nextDelay = Math.max(0, this._nextTickAt - performance.now());
    this._scheduleTick(Math.min(nextDelay, this.chunkMs));
  }

  _sendOneChunk() {
    if (!this.audioData) return;

    if (this.position >= this.audioData.length) {
      console.log("[DummyCapture] Reached end of file, starting 10s gap");
      this.isInGap = true;
      this.position = 0;

      this._gapTimer = setTimeout(() => {
        if (!this._running) return;
        console.log("[DummyCapture] Gap complete, restarting playback");
        this.isInGap = false;
        this._nextTickAt = performance.now(); // reset pacing anchor after gap
      }, this.gapMs);

      return;
    }

    const endPos = Math.min(this.position + this.chunkSize, this.audioData.length);
    const chunk = this.audioData.subarray(this.position, endPos);
    this.position = endPos;

    // Pad final chunk with silence
    let finalChunk;
    if (chunk.length === this.chunkSize) {
      // Avoid allocation on the hot path when full chunk
      finalChunk = chunk;
    } else {
      finalChunk = new Int16Array(this.chunkSize);
      finalChunk.set(chunk);
    }

    const bytes = new Uint8Array(finalChunk.buffer, finalChunk.byteOffset, finalChunk.byteLength);
    const base64 = base64FromBytes(bytes);

    this.onAudioFrame({
      data: base64,
      timestamp_ms: Date.now(),
    });
  }
}
