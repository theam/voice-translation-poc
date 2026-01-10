class ParticipantList extends HTMLElement {
  setData(participants) {
    this.participants = participants;
    this.render();
  }

  connectedCallback() {
    this.render();
  }

  render() {
    const participants = this.participants || [];
    this.innerHTML = `
      <section class="card">
        <h2>Participants</h2>
        ${participants.length === 0 ? "<p class=\"muted\">No participants yet.</p>" : ""}
        <ul class="list">
          ${participants.map((participant) => `
            <li>
              <strong>${participant.display_name}</strong>
              <span class="muted">${participant.participant_id}</span>
            </li>
          `).join("")}
        </ul>
      </section>
    `;
  }
}

customElements.define("participant-list", ParticipantList);
