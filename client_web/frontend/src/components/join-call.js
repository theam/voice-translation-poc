import { updateState } from "../state.js";

export class JoinCall extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.error = "";
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

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        form { display: grid; gap: 12px; }
        .error { color: #ff7b7b; }
      </style>
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
    `;

    this.shadowRoot.querySelector("form").addEventListener("submit", this.handleJoin.bind(this));
  }
}

customElements.define("join-call", JoinCall);
