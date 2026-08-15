import { cookies, headers } from "next/headers";
import { NextResponse } from "next/server";

/**
 * The basket, proxied.
 *
 * Public pages are rendered server-side and the browser never talks to the API
 * directly — no CORS, no public API surface. A basket is the one interactive
 * thing on a club site, so it goes through here instead: the Host the visitor
 * arrived on is forwarded, and the API resolves the club from it exactly as it
 * does for a page render.
 *
 * The cart token lives in an httpOnly cookie. The client never sees it, which
 * means a script on the page cannot lift somebody's basket, and the component
 * does not have to carry a token around.
 */

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";
const COOKIE = "footbola_cart";

async function upstream(path: string, init: RequestInit = {}) {
  const incoming = await headers();
  const jar = await cookies();
  const token = jar.get(COOKIE)?.value;

  const response = await fetch(`${API}/api/v1/public${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // The club is decided by the domain, never by a parameter.
      "X-Forwarded-Host": incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "",
      ...(token ? { "X-Cart-Token": token } : {}),
    },
    cache: "no-store",
  });

  const body = await response.json().catch(() => ({}));
  return { response, body, jar };
}

/** Hand back a token the API just minted, so the next request finds the basket. */
function withToken(body: unknown, jar: Awaited<ReturnType<typeof cookies>>, status = 200) {
  const token = (body as { token?: string })?.token;
  if (token) {
    jar.set(COOKIE, token, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 14, // matches the cart's own lifetime
    });
  }
  return NextResponse.json(body, { status });
}

export async function GET() {
  const { response, body, jar } = await upstream("/basket");
  return withToken(body, jar, response.status);
}

export async function PUT(request: Request) {
  const payload = await request.json();
  const { response, body, jar } = await upstream("/basket/lines", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  return withToken(body, jar, response.status);
}
