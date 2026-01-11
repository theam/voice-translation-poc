import { createCall } from "../api.js";
import { updateState } from "../state.js";

export class CreateCall extends HTMLElement {
  static get observedAttributes() {
    return ["call-code"];
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.services = {};
    this.providers = [];
    this.bargeInModes = [];
    this.error = "";
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (name === "call-code" && oldValue !== newValue) {
      this.render();
    }
  }

  setOptions({ services, providers, bargeInModes }) {
    this.services = services;
    this.providers = providers;
    this.bargeInModes = bargeInModes;
    this.render();
  }

  async handleCreate(event) {
    event.preventDefault();
    const service = this.shadowRoot.querySelector("select[name=service]").value;
    const provider = this.shadowRoot.querySelector("select[name=provider]").value;
    const bargeIn = this.shadowRoot.querySelector("select[name=barge_in]").value;
    this.error = "";

    try {
      const result = await createCall(service, provider, bargeIn);
      updateState({ callCode: result.call_code });
      this.render();
    } catch (err) {
      this.error = err.message;
      this.render();
    }
  }

  render() {
    const callCode = this.getAttribute("call-code") || "";
    this.shadowRoot.innerHTML = `
      <style>
        form { display: grid; gap: 12px; }
        .error { color: #ff7b7b; }
        .call-code { font-weight: 600; }
      </style>
      <div>
        <h2>Create call</h2>
        <form>
          <label>
            Translation Service
            <select name="service">
              ${Object.keys(this.services).map((serviceName) => `<option value="${serviceName}">${serviceName}</option>`).join("")}
            </select>
          </label>
          <label>
            Provider
            <select name="provider">
              ${this.providers.map((provider) => `<option value="${provider}">${provider}</option>`).join("")}
            </select>
          </label>
          <label>
            Barge-in mode
            <select name="barge_in">
              ${this.bargeInModes.map((mode) => `<option value="${mode}">${mode}</option>`).join("")}
            </select>
          </label>
          <button type="submit">Create call</button>
          ${this.error ? `<div class="error">${this.error}</div>` : ""}
          ${callCode ? `<div class="call-code">Call code: ${callCode}</div>` : ""}
        </form>
      </div>
    `;

    this.shadowRoot.querySelector("form").addEventListener("submit", this.handleCreate.bind(this));
  }
}

customElements.define("create-call", CreateCall);
