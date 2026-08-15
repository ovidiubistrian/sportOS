import { cookies, headers } from "next/headers";
import { NextResponse } from "next/server";

import { ACCESS_COOKIE, forget } from "@/lib/auth";

/**
 * The account, proxied.
 *
 * Same shape as the basket proxy: the browser talks to this app, this app
 * talks to the API, and the token stays in an httpOnly cookie the page's
 * JavaScript cannot read. The club is decided by the Host, never by anything
 * the form posts.
 */

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

async function upstream(method: string, body?: unknown) {
  const incoming = await headers();
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) return null;

  return fetch(`${API}/api/v1/public/account`, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "X-Forwarded-Host": incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
}

export async function PUT(request: Request) {
  const response = await upstream("PUT", await request.json());
  if (!response) return NextResponse.json({ code: "UNAUTHENTICATED" }, { status: 401 });
  return NextResponse.json(await response.json().catch(() => ({})), {
    status: response.status,
  });
}

export async function DELETE() {
  const response = await upstream("DELETE");
  if (!response) return NextResponse.json({ code: "UNAUTHENTICATED" }, { status: 401 });
  // Closing the relationship also ends the session on this site: staying signed
  // in to an account that no longer exists here would only offer to create it
  // again on the next page load.
  const out = new NextResponse(null, { status: response.ok ? 204 : response.status });
  return response.ok ? forget(out) : out;
}
