import { headers } from "next/headers";
import { NextResponse } from "next/server";

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

/** Proxied for the same reason as the basket: the browser never talks to the API. */
export async function POST(request: Request) {
  const incoming = await headers();
  const response = await fetch(`${API}/api/v1/public/newsletter`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Forwarded-Host": incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "",
    },
    body: JSON.stringify(await request.json()),
    cache: "no-store",
  });
  return NextResponse.json(await response.json().catch(() => ({})), {
    status: response.status,
  });
}
