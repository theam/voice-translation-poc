import { fetchTestSettings } from "../api.js";
import { getState, subscribe } from "../state.js";
import "./join-call.js";
import "./call-room.js";
import "./event-log.js";
import "./participant-list.js";
import "./translation-service-panel.js";

export class AppShell extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.unsubscribe = null;
    this.settings = { services: {}, providers: [], barge_in_modes: [] };
  }

  connectedCallback() {
    this.loadSettings();
    this.unsubscribe = subscribe(() => this.updateFromState());
    this.render();
  }

  disconnectedCallback() {
    if (this.unsubscribe) {
      this.unsubscribe();
    }
  }

  async loadSettings() {
    try {
      this.settings = await fetchTestSettings();
    } catch (err) {
      this.settings = {
        services: {
          "VT Translation Service": "ws://localhost:8080",
          "Capco": "ws://localhost:9090",
        },
        providers: [
          "openai",
          "voice_live",
          "live_interpreter_spanish",
          "live_interpreter_english",
          "role_based_li_en_es",
        ],
        barge_in_modes: ["play_through"],
      };
    }
    // Don't call render() here - just update the create-call component
    // to avoid destroying join-call and call-room components
    this.updateSettings();
  }

  updateSettings() {
    // Update translation-service-panel component with new settings
    const translationPanel = this.shadowRoot.querySelector("translation-service-panel");
    if (translationPanel) {
      translationPanel.setOptions({
        services: this.settings.services,
        providers: this.settings.providers,
        bargeInModes: this.settings.barge_in_modes,
      });
    }
  }

  async handleCreateCall() {
    try {
      const { createSimpleCall } = await import("../api.js");
      const result = await createSimpleCall();

      // Update the join-call component with the new call code
      const joinCall = this.shadowRoot.querySelector("join-call");
      if (joinCall) {
        const input = joinCall.shadowRoot.querySelector("input[name=call_code]");
        if (input) {
          input.value = result.call_code;
          input.focus();
        }
        // Refresh recent calls
        await joinCall.loadRecentCalls();
        joinCall.render();
      }
    } catch (err) {
      console.error("Failed to create call:", err);
    }
  }

  updateFromState() {
    // Nothing to update from state changes for now
  }

  render() {
    const state = getState();
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: "Inter", system-ui, sans-serif;
          color: #e7e9ee;
          background: #0a0b0f;
          min-height: 100vh;
          padding: 32px;
        }
        h1 { margin-bottom: 16px; }
        main { display: grid; gap: 24px; max-width: 900px; margin: 0 auto; }
        .grid { display: grid; gap: 24px; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); }
        section { background: #141923; padding: 16px; border-radius: 12px; }
        .create-call-button {
          width: 100%;
          background: #2563eb;
          color: white;
          border: none;
          border-radius: 8px;
          padding: 14px 24px;
          font-size: 16px;
          font-weight: 600;
          cursor: pointer;
          transition: background 0.2s;
        }
        .create-call-button:hover {
          background: #1d4ed8;
        }
      </style>
      <main>
        <h1>ACS Emulator Web Client</h1>
        <button class="create-call-button">Create New Call</button>
        <div class="grid">
          <section>
            <join-call></join-call>
          </section>
          <section>
            <translation-service-panel></translation-service-panel>
          </section>
        </div>
        <section>
          <call-room></call-room>
        </section>
      </main>
    `;

    const translationPanel = this.shadowRoot.querySelector("translation-service-panel");
    if (translationPanel) {
      translationPanel.setOptions({
        services: this.settings.services,
        providers: this.settings.providers,
        bargeInModes: this.settings.barge_in_modes,
      });
    }

    // Add event listener for create call button
    const createButton = this.shadowRoot.querySelector(".create-call-button");
    if (createButton) {
      createButton.addEventListener("click", () => this.handleCreateCall());
    }
  }
}

customElements.define("app-shell", AppShell);
