import { fetchTestSettings, createCall } from "../api";
import { getRoute } from "../router";
import { getState, subscribe, updateState } from "../state";
import "./create-call";
import "./join-call";
import "./call-room";

class AppShell extends HTMLElement {
  connectedCallback() {
    this.innerHTML = "<main></main>";
    this.main = this.querySelector("main");
    this.renderBound = this.render.bind(this);
    this.unsubscribe = subscribe(() => this.render());
    window.addEventListener("popstate", this.renderBound);
    this.loadSettings();
    this.main.addEventListener("create-call", (event) => this.handleCreate(event));
    this.main.addEventListener("join-call", (event) => this.handleJoin(event));
  }

  disconnectedCallback() {
    this.unsubscribe?.();
    window.removeEventListener("popstate", this.renderBound);
  }

  async loadSettings() {
    try {
      const data = await fetchTestSettings();
      updateState({
        settings: data,
        provider: data.providers[0] || "",
        bargeIn: data.barge_in[0] || "",
        settingsError: null
      });
    } catch (error) {
      updateState({ settingsError: String(error) });
    }
  }

  async handleCreate(event) {
    const { provider, bargeIn } = event.detail;
    updateState({ createError: null });
    try {
      const result = await createCall(provider, bargeIn);
      updateState({ callCode: result.call_code });
    } catch (error) {
      updateState({ createError: String(error) });
    }
  }

  handleJoin(event) {
    const { displayName, callCode } = event.detail;
    updateState({ joinError: null, displayName, callCode });
    const callRoom = this.main.querySelector("call-room");
    callRoom?.startSession({ displayName, callCode });
  }

  render() {
    if (!this.main) return;
    const state = getState();
    const route = getRoute();

    if (route.name === "create") {
      this.main.innerHTML = `
        <app-create-call></app-create-call>
      `;
      const component = this.main.querySelector("app-create-call");
      component?.setData({
        settings: state.settings,
        provider: state.provider,
        bargeIn: state.bargeIn,
        callCode: state.callCode,
        settingsError: state.settingsError,
        createError: state.createError
      });
      return;
    }

    this.main.innerHTML = `
      <app-join-call></app-join-call>
      <call-room></call-room>
    `;

    const join = this.main.querySelector("app-join-call");
    join?.setData({
      displayName: state.displayName,
      callCode: state.callCode || route.callCode,
      joinError: state.joinError
    });

    const callRoom = this.main.querySelector("call-room");
    callRoom?.setData({ routeCallCode: route.callCode });
  }
}

customElements.define("app-shell", AppShell);
