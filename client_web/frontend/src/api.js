export async function fetchTestSettings() {
  const response = await fetch("/api/test-settings");
  if (!response.ok) {
    throw new Error("Failed to load test settings");
  }
  return response.json();
}

export async function fetchRecentCalls() {
  const response = await fetch("/api/recent-calls");
  if (!response.ok) {
    throw new Error("Failed to load recent calls");
  }
  return response.json();
}

export async function createSimpleCall() {
  const response = await fetch("/api/call/simple", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) {
    const payload = await response.json();
    throw new Error(payload.detail || "Failed to create call");
  }
  return response.json();
}

export async function createCall(service, provider, bargeIn) {
  const response = await fetch("/api/call/create", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ service, provider, barge_in: bargeIn }),
  });
  if (!response.ok) {
    const payload = await response.json();
    throw new Error(payload.detail || "Failed to create call");
  }
  return response.json();
}

export async function addTranslationService(callCode, service, provider, bargeIn) {
  const response = await fetch(`/api/call/${encodeURIComponent(callCode)}/translation-service`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ service, provider, barge_in: bargeIn }),
  });
  if (!response.ok) {
    const payload = await response.json();
    throw new Error(payload.detail || "Failed to add translation service");
  }
  return response.json();
}

export async function removeTranslationService(callCode) {
  const response = await fetch(`/api/call/${encodeURIComponent(callCode)}/translation-service`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const payload = await response.json();
    throw new Error(payload.detail || "Failed to remove translation service");
  }
  return response.json();
}
