export class ParticipantList extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.participants = [];
  }

  connectedCallback() {
    this.render();
  }

  setParticipants(list) {
    this.participants = list;
    this.render();
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        ul { list-style: none; padding: 0; margin: 0; }
        li { padding: 6px 0; border-bottom: 1px solid #1d1f24; }
      </style>
      <ul>
        ${this.participants.map((participant) => `<li>${participant}</li>`).join("")}
      </ul>
    `;
  }
}

customElements.define("participant-list", ParticipantList);
