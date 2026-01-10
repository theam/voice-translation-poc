import { updateState } from "../state";

class JoinCall extends HTMLElement {
  setData(data) {
    this.data = data;
    this.render();
  }

  connectedCallback() {
    this.render();
  }

  render() {
    if (!this.data) return;
    const { displayName, callCode, joinError } = this.data;

    this.innerHTML = `
      <section class="card column">
        <h1>Join Call</h1>
        <label>
          Display name
          <input name="displayName" value="${displayName || ""}" />
        </label>
        <label>
          Call code
          <input name="callCode" value="${callCode || ""}" />
        </label>
        <button type="button" class="join">Join</button>
        ${joinError ? `<p class="muted">${joinError}</p>` : ""}
      </section>
    `;

    const displayInput = this.querySelector("input[name='displayName']");
    const callInput = this.querySelector("input[name='callCode']");
    displayInput.addEventListener("input", (event) => updateState({ displayName: event.target.value }));
    callInput.addEventListener("input", (event) => updateState({ callCode: event.target.value }));

    this.querySelector("button.join")?.addEventListener("click", () => {
      const nameValue = displayInput.value.trim();
      const codeValue = callInput.value.trim();
      if (!nameValue || !codeValue) {
        updateState({ joinError: "Display name and call code are required" });
        return;
      }
      this.dispatchEvent(new CustomEvent("join-call", {
        bubbles: true,
        detail: { displayName: nameValue, callCode: codeValue }
      }));
    });
  }
}

customElements.define("app-join-call", JoinCall);
