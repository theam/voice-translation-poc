import { pcm16ToFloat32 } from "./pcm16.js";

/**
 * PlaybackQueue receives audio in ACS standard format and converts it for playback.
 *
 * Conversion pipeline:
 * 1. Receive 16kHz mono PCM16 (ACS standard format) as base64
 * 2. Decode base64 → Uint8Array → PCM16 (Int16Array)
 * 3. Convert PCM16 to Float32Array
 * 4. Resample from 16kHz to hardware rate (typically 48kHz)
 * 5. Create AudioBuffer at hardware rate for Web Audio API
 * 6. Schedule for playback with minimal latency buffering
 *
 * Input: 16kHz mono PCM16 (ACS standard format enforced by backend)
 * Output: Hardware rate mono Float32 for speakers
 *
 * Note: This class is used by MultiParticipantAudioManager which provides
 * a shared AudioContext for automatic mixing of multiple participant streams.
 */
export class PlaybackQueue {
  /**
   * @param {AudioContext} audioContext - Shared AudioContext from MultiParticipantAudioManager
   */
  constructor(audioContext) {
    if (!audioContext) {
      throw new Error("AudioContext is required");
    }
    this.context = audioContext;
    this.buffer = []; // Array of AudioBuffers waiting to be played
    this.nextScheduleTime = 0;
    this.isPlaying = false;
    this.inputSampleRate = 16000; // ACS standard: 16kHz mono PCM16
    this.minBufferDuration = 0.2; // Start playing when we have 200ms buffered
    this.maxScheduleAhead = 1.0; // Maximum time to schedule ahead (1 second)
    this.maxBufferDuration = 3.0; // Maximum total buffer (drop old audio if exceeded)
    this.schedulerInterval = null;
  }

  async enqueue(pcmBytes) {

    // Convert PCM16 (Int16) → Float32 at 16kHz
    const floatData = pcm16ToFloat32(pcmBytes.buffer);

    // Resample from 16kHz → hardware rate (e.g., 48kHz)
    const resampleRatio = this.context.sampleRate / this.inputSampleRate;
    const resampledData = this.resample(floatData, resampleRatio);

    // Create AudioBuffer at hardware rate for Web Audio API
    const buffer = this.context.createBuffer(1, resampledData.length, this.context.sampleRate);
    buffer.copyToChannel(resampledData, 0);

    // Check if buffer would exceed maximum
    let bufferedDuration = this.getBufferedDuration();
    if (bufferedDuration + buffer.duration > this.maxBufferDuration) {
      // Drop oldest chunks until we have room for the new one
      let droppedCount = 0;
      while (bufferedDuration + buffer.duration > this.maxBufferDuration && this.buffer.length > 0) {
        const dropped = this.buffer.shift();
        bufferedDuration -= dropped.duration;
        droppedCount++;
      }
      console.warn(`Buffer overflow: dropped ${droppedCount} old chunks (${(this.maxBufferDuration - bufferedDuration).toFixed(3)}s freed)`);
    }

    // Add to buffer
    this.buffer.push(buffer);
    bufferedDuration = this.getBufferedDuration();

    // Start playback if we have enough buffered and not already playing
    if (!this.isPlaying && bufferedDuration >= this.minBufferDuration) {
      console.log(`Starting playback with ${bufferedDuration.toFixed(3)}s buffered`);
      this.startPlayback();
    }
  }

  getBufferedDuration() {
    return this.buffer.reduce((sum, buf) => sum + buf.duration, 0);
  }

  startPlayback() {
    if (this.isPlaying) return;

    this.isPlaying = true;
    this.nextScheduleTime = this.context.currentTime;

    // Schedule audio every 25ms to maintain smooth playback
    this.schedulerInterval = setInterval(() => {
      this.scheduleBufferedAudio();
    }, 25);

    // Schedule immediately
    this.scheduleBufferedAudio();
  }

  scheduleBufferedAudio() {
    // Schedule chunks that are within the lookahead window
    while (this.buffer.length > 0) {
      const scheduleDelta = this.nextScheduleTime - this.context.currentTime;

      // Don't schedule more than maxScheduleAhead (1 second) into the future
      // This allows buffering for network bursts while keeping latency under control
      if (scheduleDelta > this.maxScheduleAhead) {
        break;
      }

      const buffer = this.buffer.shift();
      const source = this.context.createBufferSource();
      source.buffer = buffer;
      source.connect(this.context.destination);

      // If we're behind current time, catch up immediately
      const startTime = Math.max(this.nextScheduleTime, this.context.currentTime);
      source.start(startTime);

      this.nextScheduleTime = startTime + buffer.duration;
    }

    // Stop the scheduler if buffer is empty and no audio is playing
    if (this.buffer.length === 0 && this.nextScheduleTime <= this.context.currentTime + 0.05) {
      console.log("Playback buffer empty");
      this.stopPlayback();
    }
  }

  stopPlayback() {
    if (this.schedulerInterval) {
      clearInterval(this.schedulerInterval);
      this.schedulerInterval = null;
    }
    this.isPlaying = false;
  }

  /**
   * Resample audio using linear interpolation.
   * For upsampling (e.g., 16kHz → 48kHz), ratio > 1 (e.g., 3.0)
   * Each output sample maps to i / ratio in input samples (interpolating)
   */
  resample(input, ratio) {
    if (Math.abs(ratio - 1.0) < 0.001) {
      return input;
    }

    const outputLength = Math.floor(input.length * ratio);
    const output = new Float32Array(outputLength);

    for (let i = 0; i < outputLength; i++) {
      const sourceIndex = i / ratio;
      const sourceIndexFloor = Math.floor(sourceIndex);
      const sourceIndexCeil = Math.min(sourceIndexFloor + 1, input.length - 1);
      const fraction = sourceIndex - sourceIndexFloor;

      // Linear interpolation between adjacent samples
      output[i] = input[sourceIndexFloor] * (1 - fraction) + input[sourceIndexCeil] * fraction;
    }

    return output;
  }

  stop() {
    this.buffer = [];
    this.stopPlayback();
    if (this.context) {
      this.nextScheduleTime = this.context.currentTime;
    }
  }
}
