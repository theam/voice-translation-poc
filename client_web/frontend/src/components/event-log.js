class EventLog extends HTMLElement {
  setData(events) {
    this.events = events;
    this.render();
  }

  connectedCallback() {
    this.render();
  }

  render() {
    const events = this.events || [];
    this.innerHTML = `
      <section class="card">
        <h2>ACS Events</h2>
        <div class="event-log">
          ${events.map((event) => `<pre>${JSON.stringify(event.event, null, 2)}</pre>`).join("")}
        </div>
      </section>
    `;
  }
}

customElements.define("event-log", EventLog);
