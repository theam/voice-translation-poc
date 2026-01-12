import { fetchRecentCalls } from "../api.js";
import { updateState, subscribe, getState } from "../state.js";

export class JoinCall extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.error = "";
    this.recentCalls = [];
    this.unsubscribe = null;
    this.lastCallCode = "";
  }

  async connectedCallback() {
    await this.loadRecentCalls();
    this.render();

    // Initialize lastCallCode to current state to avoid false positives
    const { callCode } = getState();
    this.lastCallCode = callCode || "";

    // Subscribe to state changes to refresh recent calls when a new call is created
    this.unsubscribe = subscribe(async () => {
      const { callCode } = getState();
      // Only reload if callCode changed (new call created)
      if (callCode && callCode !== this.lastCallCode) {
        this.lastCallCode = callCode;
        await this.loadRecentCalls();
        this.render();
      }
    });
  }

  disconnectedCallback() {
    if (this.unsubscribe) {
      this.unsubscribe();
    }
  }

  async loadRecentCalls() {
    try {
      const response = await fetchRecentCalls();
      this.recentCalls = response.calls || [];
    } catch (err) {
      console.error("Failed to load recent calls:", err);
      this.recentCalls = [];
    }
  }

  handleCallClick(callCode) {
    const input = this.shadowRoot.querySelector("input[name=call_code]");
    if (input) {
      input.value = callCode;
      input.focus();
    }
  }

  handleJoin(event) {
    event.preventDefault();
    const callCode = this.shadowRoot.querySelector("input[name=call_code]").value.trim().toUpperCase();
    const participantId = this.shadowRoot.querySelector("input[name=participant_id]").value.trim();

    if (!callCode || !participantId) {
      this.error = "Call code and participant name are required.";
      this.render();
      return;
    }

    this.error = "";
    updateState({ callCode, participantId });
  }

  formatTime(isoString) {
    try {
      const date = new Date(isoString);
      const now = new Date();
      const diffMs = now - date;
      const diffMins = Math.floor(diffMs / 60000);

      if (diffMins < 1) return "just now";
      if (diffMins < 60) return `${diffMins}m ago`;
      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours}h ago`;
      return date.toLocaleDateString();
    } catch {
      return "";
    }
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        .container { display: grid; gap: 16px; }
        form { display: grid; gap: 12px; }
        .error { color: #ff7b7b; }
        .recent-calls { margin-top: 16px; }
        .recent-calls h3 { margin: 0 0 8px 0; font-size: 14px; color: #8a9099; }
        .call-list { display: grid; gap: 8px; max-height: 300px; overflow-y: auto; }
        .call-item {
          background: #0b0d10;
          border: 1px solid #1d1f24;
          border-radius: 6px;
          padding: 10px;
          cursor: pointer;
          transition: background 0.2s, border-color 0.2s;
        }
        .call-item:hover {
          background: #141923;
          border-color: #2a2d35;
        }
        .call-code {
          font-weight: 600;
          font-size: 16px;
          margin-bottom: 4px;
        }
        .call-meta {
          font-size: 12px;
          color: #8a9099;
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
        }
        .call-meta span {
          display: inline-block;
        }
        .active-indicator {
          color: #4ade80;
        }
        .empty-state {
          text-align: center;
          color: #8a9099;
          font-size: 13px;
          padding: 20px;
        }
      </style>
      <div class="container">
        <div>
          <h2>Join call</h2>
          <form>
            <label>
              Call code
              <input name="call_code" placeholder="ABC123" />
            </label>
            <label>
              Participant name
              <input name="participant_id" placeholder="Alex" />
            </label>
            <button type="submit">Join call</button>
            ${this.error ? `<div class="error">${this.error}</div>` : ""}
          </form>
        </div>

        ${this.recentCalls.length > 0 ? `
          <div class="recent-calls">
            <h3>Recent Calls</h3>
            <div class="call-list">
              ${this.recentCalls.map(call => `
                <div class="call-item" data-call-code="${call.call_code}">
                  <div class="call-code">${call.call_code}</div>
                  <div class="call-meta">
                    <span>${call.service}</span>
                    <span>${call.provider}</span>
                    ${call.is_active ? `<span class="active-indicator">● ${call.participant_count} active</span>` : ''}
                    <span>${this.formatTime(call.created_at)}</span>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        ` : `
          <div class="recent-calls">
            <h3>Recent Calls</h3>
            <div class="empty-state">No recent calls. Create a call to get started.</div>
          </div>
        `}
      </div>
    `;

    this.shadowRoot.querySelector("form").addEventListener("submit", this.handleJoin.bind(this));

    // Add click handlers to recent call items
    this.shadowRoot.querySelectorAll(".call-item").forEach(item => {
      item.addEventListener("click", () => {
        const callCode = item.dataset.callCode;
        this.handleCallClick(callCode);
      });
    });
  }
}

customElements.define("join-call", JoinCall);
