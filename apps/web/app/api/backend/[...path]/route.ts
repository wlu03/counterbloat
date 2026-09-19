// Forwards browser requests to the backend and adds the API key on the server.
import { NextRequest } from "next/server";

const BASE = process.env.COUNTERCHECK_API_URL ?? "http://localhost:8000";

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  // Another site's page must not be able to send requests that receive the API key.
  const site = request.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") {
    return new Response("cross-site request refused", { status: 403 });
  }
  const { path } = await context.params;
  const headers: Record<string, string> = {
    "X-API-Key": process.env.COUNTERCHECK_API_KEY ?? "",
    "Content-Type": "application/json",
  };
  const idempotency = request.headers.get("Idempotency-Key");
  if (idempotency) headers["Idempotency-Key"] = idempotency;
  const response = await fetch(`${BASE}/${path.join("/")}`, {
    method: request.method,
    headers,
    body: request.method === "GET" ? undefined : await request.text(),
    cache: "no-store",
  });
  return new Response(await response.text(), {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}

export { forward as GET, forward as POST };
