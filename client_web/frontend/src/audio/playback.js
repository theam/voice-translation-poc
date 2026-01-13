// playback.js
import { pcm16ToFloat32 } from "./pcm16.js";

/**
 * PlaybackQueue (improved)
 *
 * Fixes for "bad first ~20s" + glitches:
 * - Flush pending audio immediately when starting (avoid coalesce stall/underruns)
 * - Use smaller coalesce window (default 60ms) to reduce startup starvation
 * - Start with slightly higher latency (250ms) and adapt down only after stable
 * - Add short fades per buffer to eliminate clicks at chunk boundaries
 * - Gain ramp-in on first start to remove initial pop
 */
export class PlaybackQueue {
  constructor(audioContext, outputNode) {
    if (!audioContext) throw new Error("AudioContext is required");

    this.context = audioContext;

    // Output routing
    this.outputNode = outputNode ?? this.context.destination;
    this.gainNode = this.context.createGain();
    this.gainNode.gain.value = 1.0;
    this.gainNode.connect(this.outputNode);

    // Format
    this.inputSampleRate = 16000;

    // Queue
    this.buffer = [];
    this.bufferedDurationSec = 0;
    this.nextScheduleTime = 0;
    this.isPlaying = false;
    this.lastEnqueueTime = 0;

    // Buffering / scheduling
    this.minBufferDuration = 0.28;      // a bit higher to reduce startup glitches
    this.targetLatencySec = 0.25;       // start higher so you don't spend 20s ramping up
    this.safetyMarginSec = 0.05;        // schedule a bit further ahead to avoid "too close to now"
    this.maxScheduleAhead = 1.0;
    this.maxBufferDuration = 3.0;
    this.gracePeriod = 0.6;
    this.lateResetSec = 0.12;

    // Adaptive jitter buffer
    this.underrunCount = 0;
    this.lastUnderrunTime = 0;
    this.stableSince = this.context.currentTime;

    // Loop detection
    this._scheduleCount = 0;
    this._lastScheduleResetTime = this.context.currentTime;

    // Chunk coalescing (smaller reduces startup starvation)
    this.coalesceChunkSec = 0.06; // 60ms
    this._pendingParts = [];
    this._pendingSamples = 0;
    this._lastFlushTime = 0; // Track last flush to prevent rapid loops

    // Click reduction (disabled for continuous streams - causes scratchy artifacts)
    // this.fadeMs = 4; // per-buffer fade in/out (2-5ms typical)

    // Startup pop reduction
    this._startedOnce = false;

    // Mute/unmute state
    this._preMuteGain = 1.0;
  }

  async enqueue(pcmBytes) {
    if (!pcmBytes || pcmBytes.byteLength === 0) return;

    const floatData = pcm16ToFloat32(pcmBytes.buffer);

    // Add to pending
    this._pendingParts.push(floatData);
    this._pendingSamples += floatData.length;

    // Normal coalescing flush
    const targetSamples = Math.max(1, Math.floor(this.coalesceChunkSec * this.inputSampleRate));
    while (this._pendingSamples >= targetSamples) {
      const slice = this._consumePendingSamples(targetSamples);
      this._pushAudioBuffer(slice);
    }

    this.lastEnqueueTime = this.context.currentTime;

    // If we are not playing yet and we have *some* audio, flush pending immediately.
    // This avoids startup underruns caused by waiting for coalesce size.
    if (!this.isPlaying) {
      // Top up buffered duration estimate with pending (approx)
      const pendingDuration = this._pendingSamples / this.inputSampleRate;
      const totalSoon = this.getBufferedDuration() + pendingDuration;

      if (totalSoon >= this.minBufferDuration) {
        // Flush ALL remaining pending now (even if < coalesce size)
        this._flushPendingAll();

        this.isPlaying = true;
        const now = this.context.currentTime;
        this.nextScheduleTime = Math.max(this.nextScheduleTime, now + this.targetLatencySec);

        // Ramp gain on first ever start to avoid initial click/pop
        if (!this._startedOnce) {
          this._startedOnce = true;
          this._rampGainIn(now);
        }
      }
    }
  }

  _rampGainIn(now) {
    try {
      const g = this.gainNode.gain;
      const current = g.value;
      g.cancelScheduledValues(now);
      // Start slightly low and ramp quickly
      g.setValueAtTime(0.0001, now);
      g.linearRampToValueAtTime(Math.max(0.2, current), now + 0.03);
      g.linearRampToValueAtTime(current, now + 0.08);
    } catch (_) {
      // ignore
    }
  }

  _flushPendingAll() {
    if (this._pendingSamples <= 0 || this._pendingParts.length === 0) return;

    // Guard: ensure we have actual data to flush
    const samplesToFlush = this._pendingSamples;
    if (samplesToFlush < 16) return; // Don't flush tiny fragments

    const slice = this._consumePendingSamples(samplesToFlush);

    // Verify we actually got data (not all zeros)
    if (slice.length === 0) return;

    this._pushAudioBuffer(slice);
  }

  _consumePendingSamples(n) {
    const out = new Float32Array(n);
    let written = 0;

    while (written < n && this._pendingParts.length > 0) {
      const head = this._pendingParts[0];
      const need = n - written;

      if (head.length <= need) {
        out.set(head, written);
        written += head.length;
        this._pendingParts.shift();
        this._pendingSamples -= head.length;
      } else {
        out.set(head.subarray(0, need), written);
        const rest = head.subarray(need);
        this._pendingParts[0] = rest;
        written += need;
        this._pendingSamples -= need;
      }
    }

    // Safety: if we exhausted parts but counter is still > 0, reset it
    if (this._pendingParts.length === 0 && this._pendingSamples !== 0) {
      console.warn(`Pending samples counter out of sync (${this._pendingSamples}), resetting`);
      this._pendingSamples = 0;
    }

    // Return only the portion we actually wrote (avoid trailing zeros)
    return written < n ? out.subarray(0, written) : out;
  }

  _applyFadesInPlace(float16k) {
    const fadeSamples = Math.max(0, Math.floor((this.fadeMs / 1000) * this.inputSampleRate));
    if (fadeSamples <= 1 || float16k.length < fadeSamples * 2) return float16k;

    // Fade in
    for (let i = 0; i < fadeSamples; i++) {
      const t = i / fadeSamples;
      float16k[i] *= t;
    }
    // Fade out
    for (let i = 0; i < fadeSamples; i++) {
      const t = (fadeSamples - i) / fadeSamples;
      const idx = float16k.length - fadeSamples + i;
      float16k[idx] *= t;
    }
    return float16k;
  }

  _pushAudioBuffer(float16k) {
    // Click reduction (disabled - causes scratchy artifacts on continuous audio)
    // this._applyFadesInPlace(float16k);

    const buffer = this.context.createBuffer(1, float16k.length, this.inputSampleRate);
    buffer.copyToChannel(float16k, 0);

    // Cap buffer (drop oldest)
    if (this.bufferedDurationSec + buffer.duration > this.maxBufferDuration) {
      let droppedCount = 0;
      while (this.bufferedDurationSec + buffer.duration > this.maxBufferDuration && this.buffer.length > 0) {
        const dropped = this.buffer.shift();
        this.bufferedDurationSec -= dropped.duration;
        droppedCount++;
      }
      if (droppedCount > 0) {
        console.warn(
          `Buffer overflow: dropped ${droppedCount} old chunks (buffer now ~${this.bufferedDurationSec.toFixed(3)}s)`
        );
      }
    }

    this.buffer.push(buffer);
    this.bufferedDurationSec += buffer.duration;
  }

  getBufferedDuration() {
    return this.bufferedDurationSec;
  }

  scheduleNext() {
    if (!this.isPlaying) {
      return this.buffer.length > 0 || this._pendingSamples > 0;
    }

    const now = this.context.currentTime;

    // If we’re too far behind, treat as a gap and jump cursor forward
    if (this.nextScheduleTime < now - this.lateResetSec) {
      this.nextScheduleTime = now + this.safetyMarginSec;
    }

    // If we are starving but still have pending (not yet coalesced), flush it
    // Guard: only flush if enough time has passed to avoid loops
    const MIN_FLUSH_INTERVAL_SEC = 0.05; // 50ms between flushes
    if (this.buffer.length === 0 && this._pendingSamples > 0) {
      if (now - this._lastFlushTime > MIN_FLUSH_INTERVAL_SEC) {
        this._lastFlushTime = now;
        this._flushPendingAll();
      }
    }

    // Underrun detection
    const willUnderrun = this.buffer.length === 0 && this.nextScheduleTime <= now + this.safetyMarginSec;
    if (willUnderrun) this._onUnderrun(now);
    else this._onStable(now);

    // Schedule within lookahead
    while (this.buffer.length > 0) {
      const scheduleDelta = this.nextScheduleTime - now;
      if (scheduleDelta > this.maxScheduleAhead) break;

      const buf = this.buffer.shift();
      this.bufferedDurationSec -= buf.duration;

      const source = this.context.createBufferSource();
      source.buffer = buf;
      source.connect(this.gainNode);

      const startTime = Math.max(this.nextScheduleTime, now + this.safetyMarginSec);
      source.start(startTime);
      this.nextScheduleTime = startTime + buf.duration;

      // Loop detection
      this._scheduleCount++;
      if (now - this._lastScheduleResetTime > 1.0) {
        if (this._scheduleCount > 100) {
          console.warn(`Possible audio loop detected: ${this._scheduleCount} schedules in 1 second`);
        }
        this._scheduleCount = 0;
        this._lastScheduleResetTime = now;
      }
    }

    if (this.buffer.length > 0 || this._pendingSamples > 0) return true;

    const audioStillPlaying = this.nextScheduleTime > now;
    const recentlyReceivedAudio = (now - this.lastEnqueueTime) < this.gracePeriod;
    if (audioStillPlaying || recentlyReceivedAudio) return true;

    this.isPlaying = false;
    return false;
  }

  _onUnderrun(now) {
    const COOLDOWN_SEC = 0.25;
    if (this.lastUnderrunTime && now - this.lastUnderrunTime < COOLDOWN_SEC) return;

    this.underrunCount++;
    this.lastUnderrunTime = now;
    this.stableSince = now;

    // Increase latency quickly early on, then cap
    const old = this.targetLatencySec;
    this.targetLatencySec = Math.min(this.targetLatencySec + 0.02, 0.50);

    if (this.targetLatencySec !== old) {
      this.nextScheduleTime = Math.max(this.nextScheduleTime, now + this.targetLatencySec);
    }
  }

  _onStable(now) {
    // Only reduce latency after a long stable period
    const STABLE_WINDOW_SEC = 12.0;
    if (now - this.stableSince < STABLE_WINDOW_SEC) return;

    const old = this.targetLatencySec;
    this.targetLatencySec = Math.max(this.targetLatencySec - 0.01, 0.14);
    this.stableSince = now;

    // no cursor jump needed when decreasing
    void old;
  }

  setVolume(value) {
    const v = Number.isFinite(value) ? value : 1.0;
    this.gainNode.gain.value = Math.max(0, v);
  }

  mute() {
    this._preMuteGain = this.gainNode.gain.value;
    this.gainNode.gain.value = 0;
  }

  unmute() {
    this.gainNode.gain.value = Number.isFinite(this._preMuteGain) ? this._preMuteGain : 1.0;
  }

  stop() {
    this.buffer = [];
    this.bufferedDurationSec = 0;
    this._pendingParts = [];
    this._pendingSamples = 0;

    this.isPlaying = false;
    if (this.context) {
      const now = this.context.currentTime;
      this.nextScheduleTime = now;
      this.lastEnqueueTime = now;
      this.stableSince = now;
      this._lastFlushTime = 0;
      this._scheduleCount = 0;
      this._lastScheduleResetTime = now;
    }
  }
}
