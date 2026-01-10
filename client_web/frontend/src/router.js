export function getRoute() {
  const path = window.location.pathname;
  if (path.startsWith("/join/")) {
    const callCode = path.replace("/join/", "");
    return { name: "join", callCode };
  }
  return { name: "create", callCode: "" };
}

export function navigate(path) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new Event("popstate"));
}
