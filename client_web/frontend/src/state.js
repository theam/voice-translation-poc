const state = {
  callCode: "",
  participantId: "",
  dummyMode: false,  // Dummy mode for testing (no mic/speakers)
  participants: [],  // All participants in the call
  connection: null,
  translationServiceConnected: false,  // Whether translation service is connected to the call
  settings: null,
  listeners: new Set(),
};

export function getState() {
  return state;
}

export function updateState(partial) {
  Object.assign(state, partial);
  for (const listener of state.listeners) {
    listener(state);
  }
}

export function subscribe(listener) {
  state.listeners.add(listener);
  return () => state.listeners.delete(listener);
}
