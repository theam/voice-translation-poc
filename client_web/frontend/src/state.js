const listeners = new Set();

const state = {
  settings: null,
  settingsError: null,
  callCode: "",
  provider: "",
  bargeIn: "",
  createError: null,
  joinError: null,
  displayName: "",
  participants: [],
  events: [],
  connected: false,
  micLevel: 0,
  muted: false,
  playParticipantAudio: true,
  playServiceAudio: true
};

export function getState() {
  return { ...state };
}

export function updateState(partial) {
  Object.assign(state, partial);
  for (const listener of listeners) {
    listener(getState());
  }
}

export function subscribe(listener) {
  listeners.add(listener);
  listener(getState());
  return () => listeners.delete(listener);
}
