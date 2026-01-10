export type TestSettings = {
  providers: string[];
  barge_in: string[];
};

export async function fetchTestSettings(): Promise<TestSettings> {
  const response = await fetch("/api/test-settings");
  if (!response.ok) {
    throw new Error("Failed to load test settings");
  }
  return response.json();
}

export async function createCall(provider: string, bargeIn: string): Promise<{ call_code: string }> {
  const response = await fetch("/api/call/create", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ provider, barge_in: bargeIn })
  });
  if (!response.ok) {
    throw new Error("Failed to create call");
  }
  return response.json();
}
