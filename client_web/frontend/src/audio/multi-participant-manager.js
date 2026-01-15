// MultiParticipantAudioManager.js
import { PlaybackQueue } from "./playback.js";

/**
 * MultiParticipantAudioManager
 *
 * Improvements implemented vs your version:
 * - Adds a master bus (GainNode) + DynamicsCompressorNode for safer mixing (prevents clipping)
 * - Routes each participant queue into the master bus (instead of directly to destination)
 * - Ensures AudioContext is resumed before creating nodes (autoplay policy)
 * - Uses a self-throttling scheduler loop (setTimeout) to avoid setInterval drift/overlap
 * - Adds basic participant controls: setVolume/mute/unmute
 * - More robust cleanup (disconnect nodes, close context safely)
 *
 * Notes:
 * - PlaybackQueue is expected to accept (audioContext, outputNode) in its constructor
 *   and connect its per-participant gain into outputNode.
 */
export class MultiParticipantAudioManager {
  constructor() {
    this.queues = new Map(); // participantId -> PlaybackQueue
    this.sharedContext = null;

    // Master mixing graph
    this.masterGain = null;
    this.masterCompressor = null;

    // Scheduler
    this._schedulerTimer = null;
    this._schedulerRunning = false;
    this._schedulerPeriodMs = 25; // target cadence (keep small for low latency)
  }

  /**
   * Enqueue audio for a specific participant.
   * Creates a new queue if participant doesn't have one yet.
   *
   * @param {string} participantId
   * @param {Uint8Array} pcmBytes
   */
  async enqueueAudio(participantId, pcmBytes) {
    const context = await this.getSharedContext();

    // Create queue if needed (route to master bus)
    if (!this.queues.has(participantId)) {
      const queue = new PlaybackQueue(context, this.masterGain);
      this.queues.set(participantId, queue);
      // console.log(`Created audio queue for participant: ${participantId}`);
    }

    // Enqueue to participant queue
    await this.queues.get(participantId).enqueue(pcmBytes);

    // Start scheduler if not already running
    this.startScheduler();
  }

  /**
   * Create (or return) shared AudioContext and master graph.
   */
  async getSharedContext() {
    if (!this.sharedContext) {
      this.sharedContext = new AudioContext();
      // console.log(`Shared AudioContext created: ${this.sharedContext.sampleRate} Hz`);
    }

    // Resume if suspended (autoplay policy)
    if (this.sharedContext.state === "suspended") {
      // console.log("Resuming suspended AudioContext...");
      await this.sharedContext.resume();
    }

    // Build master graph once, after context is usable
    if (!this.masterGain || !this.masterCompressor) {
      this._buildMasterGraph();
    }

    return this.sharedContext;
  }

  /**
   * Master graph:
   * participant -> PlaybackQueue.gainNode -> masterGain -> masterCompressor -> destination
   */
  _buildMasterGraph() {
    const ctx = this.sharedContext;
    if (!ctx) throw new Error("AudioContext must exist before building graph");

    // Clean up if rebuilding
    try {
      this.masterGain?.disconnect();
      this.masterCompressor?.disconnect();
    } catch (_) {}

    this.masterGain = ctx.createGain();
    this.masterGain.gain.value = 1.0;

    // DynamicsCompressorNode is a decent "safety limiter" for multi-party mixes.
    // (No perfect limiter in WebAudio without an AudioWorklet, but this prevents most clipping.)
    this.masterCompressor = ctx.createDynamicsCompressor();
    // Keep defaults unless you have a reason to tune.
    // You can tune later if you want tighter limiting.

    this.masterGain.connect(this.masterCompressor);
    this.masterCompressor.connect(ctx.destination);
  }

  /**
   * Start the centralized scheduler that coordinates all participant queues.
   * Uses a self-throttling loop to avoid setInterval drift/overlaps.
   */
  startScheduler() {
    if (this._schedulerRunning) return;
    this._schedulerRunning = true;

    const tick = () => {
      // If context is gone, stop
      if (!this.sharedContext) {
        this._stopSchedulerInternal();
        return;
      }

      const anyQueueActive = this.scheduleAllQueues();

      if (anyQueueActive) {
        this._schedulerTimer = setTimeout(tick, this._schedulerPeriodMs);
      } else {
        this._stopSchedulerInternal();
      }
    };

    // Run immediately
    tick();
  }

  _stopSchedulerInternal() {
    if (this._schedulerTimer) {
      clearTimeout(this._schedulerTimer);
      this._schedulerTimer = null;
    }
    this._schedulerRunning = false;
  }

  /**
   * Schedule audio for all participant queues.
   *
   * @returns {boolean} true if any queue still active (needs more scheduling)
   */
  scheduleAllQueues() {
    let anyQueueActive = false;

    for (const [, queue] of this.queues) {
      try {
        const hasMore = queue.scheduleNext();
        if (hasMore) anyQueueActive = true;
      } catch (err) {
        console.error("Error scheduling queue:", err);
        // Keep manager alive; a single queue failure shouldn't kill playback for others.
      }
    }

    return anyQueueActive;
  }

  /**
   * Participant controls (require PlaybackQueue methods)
   */
  setParticipantVolume(participantId, volume) {
    const q = this.queues.get(participantId);
    if (!q) return false;
    if (typeof q.setVolume === "function") q.setVolume(volume);
    return true;
  }

  muteParticipant(participantId) {
    const q = this.queues.get(participantId);
    if (!q) return false;
    if (typeof q.mute === "function") q.mute();
    return true;
  }

  unmuteParticipant(participantId) {
    const q = this.queues.get(participantId);
    if (!q) return false;
    if (typeof q.unmute === "function") q.unmute();
    return true;
  }

  /**
   * Remove a participant's queue and stop their audio.
   */
  removeParticipant(participantId) {
    const queue = this.queues.get(participantId);
    if (queue) {
      try {
        queue.stop();
        // If PlaybackQueue exposes its gainNode, you could disconnect it here.
        // (Not required, but can help avoid lingering nodes.)
        if (queue.gainNode && typeof queue.gainNode.disconnect === "function") {
          queue.gainNode.disconnect();
        }
      } catch (err) {
        console.warn(`Error stopping queue for ${participantId}:`, err);
      }
      this.queues.delete(participantId);
      // console.log(`Removed audio queue for participant: ${participantId}`);
    }

    // If nothing left, scheduler can stop naturally; but we can nudge it
    if (this.queues.size === 0) {
      this._stopSchedulerInternal();
    }
  }

  /**
   * Stop all queues and clean up resources.
   */
  async stopAll() {
    this._stopSchedulerInternal();

    for (const [, queue] of this.queues) {
      try {
        queue.stop();
        if (queue.gainNode && typeof queue.gainNode.disconnect === "function") {
          queue.gainNode.disconnect();
        }
      } catch (_) {}
    }
    this.queues.clear();

    // Disconnect master nodes
    try {
      this.masterGain?.disconnect();
      this.masterCompressor?.disconnect();
    } catch (_) {}

    this.masterGain = null;
    this.masterCompressor = null;

    // Close shared context
    if (this.sharedContext) {
      try {
        await this.sharedContext.close();
      } catch (_) {
        // close can throw if already closed; ignore
      }
      this.sharedContext = null;
    }
  }

  /**
   * Get list of participants with active queues.
   */
  getActiveParticipants() {
    return Array.from(this.queues.keys());
  }
}
