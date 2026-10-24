// Proxies questions to the PlainPath FastAPI backend so the browser only talks to this origin.
// BACKEND_URL is server-only (no NEXT_PUBLIC_ prefix), read at request time.

const DEFAULT_BACKEND = "http://localhost:8000";
const TIMEOUT_MS = 90_000;

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const backend = (process.env.BACKEND_URL ?? DEFAULT_BACKEND).replace(/\/$/, "");
  let res: Response;
  try {
    res = await fetch(`${backend}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    return Response.json({ error: "The PlainPath service is not reachable right now." }, { status: 502 });
  }
  try {
    return Response.json(await res.json(), { status: res.status });
  } catch {
    // Backend answered but not with JSON (e.g. an unhandled 500): keep its status, give a readable message.
    return Response.json({ error: "Something went wrong while preparing the answer. Please try again." }, { status: res.status >= 400 ? res.status : 502 });
  }
}
