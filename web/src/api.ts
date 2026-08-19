// Thin fetch wrapper. Replace with real domain calls as endpoints land in app/main.py.

export type HealthResponse = { status: string };

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch("/health");
  if (!res.ok) {
    throw new Error(`GET /health failed: ${res.status}`);
  }
  return res.json();
}
