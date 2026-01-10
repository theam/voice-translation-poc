export class EventLog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.events = [];
  }

  addEvent(message) {
    this.events.unshift({ message, timestamp: new Date().toLocaleTimeString() });
    this.render();
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        .log {
          background: #0b0d10;
          border: 1px solid #1d1f24;
          border-radius: 8px;
          padding: 12px;
          max-height: 200px;
          overflow-y: auto;
          font-size: 12px;
        }
        .entry { margin-bottom: 8px; }
        .time { color: #8a9099; margin-right: 6px; }
      </style>
      <div class="log">
        ${this.events
          .map((event) => `<div class="entry"><span class="time">${event.timestamp}</span>${event.message}</div>`)
          .join("")}
      </div>
    `;
  }
}

customElements.define("event-log", EventLog);
