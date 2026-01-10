const state = {
  callCode: "",
  participantId: "",
  connection: null,
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
