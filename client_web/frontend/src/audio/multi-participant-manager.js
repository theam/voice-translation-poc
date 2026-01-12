import { PlaybackQueue } from "./playback.js";

/**
 * Manages per-participant audio queues with automatic mixing.
 *
 * Each participant (including translation service) gets their own PlaybackQueue.
 * All queues share a single AudioContext and connect to the same destination.
 * Web Audio API automatically mixes overlapping audio from multiple sources.
 *
 * Architecture:
 * - Map of participantId → PlaybackQueue
 * - Shared AudioContext across all queues
 * - Each queue schedules independently
 * - Automatic mixing at hardware level
 * - Translation service uses ID: "vt-translation-service"
 */
export class MultiParticipantAudioManager {
  constructor() {
    this.queues = new Map(); // participantId -> PlaybackQueue
    this.sharedContext = null;
  }

  /**
   * Enqueue audio for a specific participant.
   * Creates a new queue if participant doesn't have one yet.
   *
   * @param {string} participantId - Participant identifier
   * @param {Uint8Array} pcmBytes - PCM16 audio bytes
   */
  async enqueueAudio(participantId, pcmBytes) {
    // Get or create queue for this participant
    if (!this.queues.has(participantId)) {
      const context = await this.getSharedContext();
      const queue = new PlaybackQueue(context);
      this.queues.set(participantId, queue);
      console.log(`Created audio queue for participant: ${participantId}`);
    }

    // Enqueue audio to participant's queue
    await this.queues.get(participantId).enqueue(pcmBytes);
  }

  /**
   * Get or create the shared AudioContext.
   * All participant queues use this same context for automatic mixing.
   *
   * @returns {Promise<AudioContext>}
   */
  async getSharedContext() {
    if (!this.sharedContext) {
      this.sharedContext = new AudioContext();
      console.log(`Shared AudioContext created: ${this.sharedContext.sampleRate} Hz`);
    }

    // Resume if suspended (autoplay policy)
    if (this.sharedContext.state === "suspended") {
      console.log("Resuming suspended AudioContext...");
      await this.sharedContext.resume();
    }

    return this.sharedContext;
  }

  /**
   * Remove a participant's queue and stop their audio.
   *
   * @param {string} participantId - Participant identifier
   */
  removeParticipant(participantId) {
    const queue = this.queues.get(participantId);
    if (queue) {
      queue.stop();
      this.queues.delete(participantId);
      console.log(`Removed audio queue for participant: ${participantId}`);
    }
  }

  /**
   * Stop all queues and clean up resources.
   * Closes the shared AudioContext and clears all participant queues.
   */
  stopAll() {
    for (const [participantId, queue] of this.queues) {
      queue.stop();
    }
    this.queues.clear();
    if (this.sharedContext) {
      this.sharedContext.close();
      this.sharedContext = null;
    }
  }

  /**
   * Get list of participants with active queues.
   *
   * @returns {string[]} Array of participant IDs
   */
  getActiveParticipants() {
    return Array.from(this.queues.keys());
  }
}
