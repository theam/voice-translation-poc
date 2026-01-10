import { updateState } from "../state";

class CreateCall extends HTMLElement {
  setData(data) {
    this.data = data;
    this.render();
  }

  connectedCallback() {
    this.render();
  }

  render() {
    if (!this.data) return;
    const { settings, provider, bargeIn, callCode, settingsError, createError } = this.data;
    this.innerHTML = `
      <div class="card column">
        <h1>ACS Emulator Web Client</h1>
        ${settingsError ? `<p class="muted">${settingsError}</p>` : ""}
        ${!settings ? "<p>Loading test settings...</p>" : ""}
        ${settings ? `
          <label>
            Provider
            <select name="provider">
              ${settings.providers.map((item) => `<option value="${item}">${item}</option>`).join("")}
            </select>
          </label>
          <label>
            Barge In
            <select name="bargeIn">
              ${settings.barge_in.map((item) => `<option value="${item}">${item}</option>`).join("")}
            </select>
          </label>
          <button type="button" class="create">Create Call</button>
          ${createError ? `<p class="muted">${createError}</p>` : ""}
          ${callCode ? `
            <div>
              <p>Call code: <span class="badge">${callCode}</span></p>
              <a href="/join/${callCode}">Join link</a>
            </div>
          ` : ""}
        ` : ""}
      </div>
    `;

    if (!settings) return;
    const providerSelect = this.querySelector("select[name='provider']");
    const bargeSelect = this.querySelector("select[name='bargeIn']");
    providerSelect.value = provider;
    bargeSelect.value = bargeIn;

    providerSelect.addEventListener("change", (event) => {
      updateState({ provider: event.target.value });
    });
    bargeSelect.addEventListener("change", (event) => {
      updateState({ bargeIn: event.target.value });
    });
    this.querySelector("button.create")?.addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("create-call", {
        bubbles: true,
        detail: {
          provider: providerSelect.value,
          bargeIn: bargeSelect.value
        }
      }));
    });
  }
}

customElements.define("app-create-call", CreateCall);
