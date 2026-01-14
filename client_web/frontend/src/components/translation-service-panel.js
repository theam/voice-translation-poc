import { addTranslationService, removeTranslationService } from "../api.js";
import { getState, subscribe, updateState } from "../state.js";

export class TranslationServicePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.services = {};
    this.providers = [];
    this.bargeInModes = [];
    this.error = "";
    this.success = "";
    this.unsubscribe = null;
  }

  connectedCallback() {
    this.unsubscribe = subscribe(() => this.render());
    this.render();
  }

  disconnectedCallback() {
    if (this.unsubscribe) {
      this.unsubscribe();
    }
  }

  setOptions({ services, providers, bargeInModes }) {
    this.services = services;
    this.providers = providers;
    this.bargeInModes = bargeInModes;
    this.render();
  }

  async handleToggleService(event) {
    event.preventDefault();
    const { callCode, translationServiceConnected } = getState();

    if (!callCode) {
      this.error = "No active call. Please join a call first.";
      this.success = "";
      this.render();
      return;
    }

    this.error = "";
    this.success = "";

    try {
      if (translationServiceConnected) {
        // Disconnect
        await removeTranslationService(callCode);
        updateState({ translationServiceConnected: false });
        this.success = "Translation service disconnected";
      } else {
        // Connect
        const service = this.shadowRoot.querySelector("select[name=service]").value;
        const provider = this.shadowRoot.querySelector("select[name=provider]").value;
        const bargeIn = this.shadowRoot.querySelector("select[name=barge_in]").value;

        await addTranslationService(callCode, service, provider, bargeIn);
        updateState({ translationServiceConnected: true });
        this.success = "Translation service connected";
      }

      this.render();
      // Clear success message after 3 seconds
      setTimeout(() => {
        this.success = "";
        this.render();
      }, 3000);
    } catch (err) {
      this.error = err.message;
      this.render();
    }
  }

  render() {
    const { callCode, translationServiceConnected } = getState();
    const isDisabled = !callCode;
    const buttonText = translationServiceConnected ? "Disconnect" : "Connect";
    const buttonClass = translationServiceConnected ? "disconnect-button" : "connect-button";

    this.shadowRoot.innerHTML = `
      <style>
        form { display: grid; gap: 12px; }
        .error { color: #ff7b7b; }
        .success { color: #4ade80; }
        .disabled-overlay {
          position: relative;
        }
        .disabled-overlay.disabled::after {
          content: '';
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          cursor: not-allowed;
        }
        .disabled-overlay.disabled * {
          pointer-events: none;
        }
        .hint {
          font-size: 12px;
          color: #8a9099;
          margin-top: -8px;
        }
        select:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .connect-button {
          padding: 5px;
          border: none;
          border-radius: 3px;
          font-weight: 600;
          cursor: pointer;
          background: #10b981;
          color: white;
        }
        .connect-button:hover:not(:disabled) {
          background: #059669;
        }
        .disconnect-button {
          background: #ef4444;
          color: white;
          padding: 5px;
          border: none;
          border-radius: 3px;
          font-weight: 600;
          cursor: pointer;
        }
        .disconnect-button:hover:not(:disabled) {
          background: #dc2626;
        }
      </style>
      <div>
        <h2>Translation Service</h2>
        <div class="disabled-overlay ${isDisabled ? 'disabled' : ''}">
          <form>
            <label>
              Translation Service
              <select name="service" ${translationServiceConnected ? 'disabled' : ''}>
                ${Object.keys(this.services).map((serviceName) => `<option value="${serviceName}">${serviceName}</option>`).join("")}
              </select>
            </label>
            <label>
              Provider
              <select name="provider" ${translationServiceConnected ? 'disabled' : ''}>
                ${this.providers.map((provider) => `<option value="${provider}">${provider}</option>`).join("")}
              </select>
            </label>
            <label>
              Barge-in mode
              <select name="barge_in" ${translationServiceConnected ? 'disabled' : ''}>
                ${this.bargeInModes.map((mode) => `<option value="${mode}">${mode}</option>`).join("")}
              </select>
            </label>
            <button type="submit" class="${buttonClass}">${buttonText}</button>
            ${!callCode ? `<div class="hint">Join a call first to connect translation service</div>` : ""}
            ${this.error ? `<div class="error">${this.error}</div>` : ""}
            ${this.success ? `<div class="success">${this.success}</div>` : ""}
          </form>
        </div>
      </div>
    `;

    const form = this.shadowRoot.querySelector("form");
    if (form) {
      form.addEventListener("submit", this.handleToggleService.bind(this));
    }
  }
}

customElements.define("translation-service-panel", TranslationServicePanel);
