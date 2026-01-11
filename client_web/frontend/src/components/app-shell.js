import { fetchTestSettings } from "../api.js";
import { getState, subscribe } from "../state.js";
import "./create-call.js";
import "./join-call.js";
import "./call-room.js";
import "./event-log.js";
import "./participant-list.js";

export class AppShell extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.unsubscribe = null;
    this.settings = { services: {}, providers: [], barge_in_modes: [] };
  }

  connectedCallback() {
    this.loadSettings();
    this.unsubscribe = subscribe(() => this.render());
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
    this.render();
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
      </style>
      <main>
        <h1>ACS Emulator Web Client</h1>
        <div class="grid">
          <section>
            <create-call></create-call>
          </section>
          <section>
            <join-call></join-call>
          </section>
        </div>
        <section>
          <call-room></call-room>
        </section>
      </main>
    `;

    const createCall = this.shadowRoot.querySelector("create-call");
    if (createCall) {
      createCall.setOptions({
        services: this.settings.services,
        providers: this.settings.providers,
        bargeInModes: this.settings.barge_in_modes,
      });
      createCall.setAttribute("call-code", state.callCode || "");
    }
  }
}

customElements.define("app-shell", AppShell);
