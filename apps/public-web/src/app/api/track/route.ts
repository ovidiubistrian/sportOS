import { headers } from "next/headers";
import { NextResponse } from "next/server";

/**
 * The analytics beacon, proxied.
 *
 * Same reason as the basket: the browser never talks to the API directly, so
 * there is no CORS to configure and no public API surface to defend. The
 * visitor's address and agent reach the API as forwarded headers, where they
 * are hashed and discarded.
 *
 * Always answers 204, even when the API is down. A measurement must never make
 * a club's website look broken.
 */

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

export async function POST(request: Request) {
  const incoming = await headers();

  try {
    await fetch(`${API}/api/v1/public/analytics/collect`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-Host": incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "",
        // The client's address as the proxy saw it. Hashed at the other end
        // with a salt that is thrown away daily; never stored.
        "X-Forwarded-For": incoming.get("x-forwarded-for") ?? "",
        "User-Agent": incoming.get("user-agent") ?? "",
      },
      body: await request.text(),
      cache: "no-store",
    });
  } catch {
    // Swallowed on purpose. See above.
  }

  return new NextResponse(null, { status: 204 });
}
