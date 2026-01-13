import { base64FromBytes } from "./pcm16.js";

/**
 * DummyCapture simulates microphone input by loading and sending a WAV file.
 *
 * Used for local testing with multiple participants without needing real audio devices.
 *
 * Behavior:
 * 1. Loads a pre-recorded WAV file (16kHz mono PCM16)
 * 2. Sends audio in 256ms chunks to match live capture timing
 * 3. After file completes, waits 10 seconds, then repeats
 * 4. Sends audio in same format as AudioCapture (base64-encoded PCM16)
 */
export class DummyCapture {
  constructor({ onAudioFrame, wavFilePath }) {
    this.onAudioFrame = onAudioFrame;
    this.wavFilePath = wavFilePath;
    this.audioData = null;
    this.position = 0;
    this.interval = null;
    // Match AudioCapture timing: ~85ms chunks to match 4096 samples at 48kHz
    // At 16kHz: 85ms = 1360 samples (rounded to 1024 for power of 2)
    this.chunkSize = 1024; // ~64ms at 16kHz
    this.chunkIntervalMs = 64; // Send chunks every 64ms to match real audio timing
    this.gapMs = 10000; // 10 second gap between file loops
    this.isInGap = false;
  }

  async start() {
    console.log(`[DummyCapture] Loading WAV file from ${this.wavFilePath}...`);

    try {
      // Load WAV file
      const response = await fetch(this.wavFilePath);
      if (!response.ok) {
        throw new Error(`Failed to load WAV file: ${response.status} ${response.statusText}`);
      }

      const arrayBuffer = await response.arrayBuffer();

      // Parse WAV file (assumes standard 44-byte header, 16kHz mono PCM16)
      // WAV header structure:
      // - Bytes 0-3: "RIFF"
      // - Bytes 4-7: File size - 8
      // - Bytes 8-11: "WAVE"
      // - Bytes 12-15: "fmt "
      // - Bytes 16-19: Format chunk size (16 for PCM)
      // - Bytes 20-21: Audio format (1 for PCM)
      // - Bytes 22-23: Number of channels
      // - Bytes 24-27: Sample rate
      // - Bytes 28-31: Byte rate
      // - Bytes 32-33: Block align
      // - Bytes 34-35: Bits per sample
      // - Bytes 36-39: "data"
      // - Bytes 40-43: Data size
      // - Bytes 44+: Audio data

      const header = new DataView(arrayBuffer, 0, 44);

      // Validate RIFF header
      const riffTag = String.fromCharCode(
        header.getUint8(0),
        header.getUint8(1),
        header.getUint8(2),
        header.getUint8(3)
      );
      if (riffTag !== "RIFF") {
        throw new Error(`Invalid WAV file: Expected RIFF header, got ${riffTag}`);
      }

      // Read format info
      const numChannels = header.getUint16(22, true);
      const sampleRate = header.getUint32(24, true);
      const bitsPerSample = header.getUint16(34, true);

      console.log(`[DummyCapture] WAV info: ${sampleRate}Hz, ${numChannels} channel(s), ${bitsPerSample}-bit`);

      // Validate format
      if (numChannels !== 1) {
        console.warn(`[DummyCapture] Expected mono audio, got ${numChannels} channels. Using first channel only.`);
      }
      if (sampleRate !== 16000) {
        console.warn(`[DummyCapture] Expected 16kHz sample rate, got ${sampleRate}Hz. Audio may not play correctly.`);
      }
      if (bitsPerSample !== 16) {
        throw new Error(`Invalid WAV file: Expected 16-bit PCM, got ${bitsPerSample}-bit`);
      }

      // Extract PCM16 data (skip 44-byte header)
      this.audioData = new Int16Array(arrayBuffer.slice(44));
      const durationSeconds = this.audioData.length / sampleRate;

      console.log(`[DummyCapture] Loaded ${this.audioData.length} samples (${durationSeconds.toFixed(1)}s)`);

      // Start sending chunks
      this.position = 0;
      this.isInGap = false;
      this.interval = setInterval(() => this.sendChunk(), this.chunkIntervalMs);

      console.log("[DummyCapture] Started sending audio chunks");
    } catch (error) {
      console.error("[DummyCapture] Failed to load WAV file:", error);
      throw error;
    }
  }

  sendChunk() {
    // If in gap period, don't send audio
    if (this.isInGap) {
      return;
    }

    // Check if we've reached the end of the file
    if (this.position >= this.audioData.length) {
      console.log("[DummyCapture] Reached end of file, starting 10s gap");
      this.isInGap = true;
      this.position = 0;

      // Schedule restart after gap
      setTimeout(() => {
        console.log("[DummyCapture] Gap complete, restarting playback");
        this.isInGap = false;
      }, this.gapMs);

      return;
    }

    // Extract chunk
    const endPos = Math.min(this.position + this.chunkSize, this.audioData.length);
    const chunk = this.audioData.slice(this.position, endPos);

    // If we have a partial chunk at the end, pad with silence
    const finalChunk = new Int16Array(this.chunkSize);
    finalChunk.set(chunk);
    // Remaining samples are already 0 (silence) from Int16Array initialization

    this.position = endPos;

    // Convert Int16Array to bytes
    const bytes = new Uint8Array(finalChunk.buffer);
    const base64 = base64FromBytes(bytes);

    // Send to callback (same format as AudioCapture)
    this.onAudioFrame({
      data: base64,
      timestamp_ms: Date.now(),
    });
  }

  stop() {
    console.log("[DummyCapture] Stopping");

    if (this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }

    this.audioData = null;
    this.position = 0;
    this.isInGap = false;
  }
}
