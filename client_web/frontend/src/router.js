export function setHash(route) {
  window.location.hash = route;
}

export function getHash() {
  return window.location.hash.replace("#", "");
}
