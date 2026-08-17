import { cookies, headers } from "next/headers";
import { NextResponse } from "next/server";

/**
 * Seat holds and ticket checkout, proxied.
 *
 * Same shape and same reasons as `/api/basket`: public pages are rendered
 * server-side, the browser never talks to the API directly, and the cart token
 * lives in an httpOnly cookie so a script on the page cannot lift somebody's
 * reservation.
 *
 * It shares the cookie with the shop deliberately. A supporter holding two
 * seats and a scarf has **one** basket and pays once — that is the whole point
 * of the ordering kernel, and two cookies would quietly undo it.
 *
 * The action lives in the body rather than in the path so the seat picker has
 * one endpoint to talk to; the alternative was four route files that differ by
 * a verb.
 */

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";
const COOKIE = "footbola_cart";

type Action = "hold" | "best-available" | "release" | "checkout";

async function upstream(path: string, init: RequestInit = {}) {
  const incoming = await headers();
  const jar = await cookies();
  const token = jar.get(COOKIE)?.value;

  const response = await fetch(`${API}/api/v1/public/tickets${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // The club is decided by the domain, never by a parameter.
      "X-Forwarded-Host": incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "",
      ...(token ? { "X-Cart-Token": token } : {}),
    },
    cache: "no-store",
  });

  const body = response.status === 204 ? {} : await response.json().catch(() => ({}));
  return { response, body, jar };
}

/**
 * Store the token the API minted, so the next request finds the same hold.
 *
 * Two hours rather than the shop's fortnight: a seat hold lasts ten minutes,
 * and a cookie that outlives every reservation it could name is only a way to
 * send a stale token.
 */
function withToken(
  body: Record<string, unknown>,
  jar: Awaited<ReturnType<typeof cookies>>,
  status: number,
) {
  const token = body.cart_token;
  if (typeof token === "string") {
    jar.set(COOKIE, token, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 2,
    });
  }
  return NextResponse.json(body, { status });
}

export async function POST(request: Request) {
  const payload = (await request.json()) as {
    action: Action;
    slug: string;
    [key: string]: unknown;
  };
  const { action, slug, ...rest } = payload;

  if (action === "release") {
    const { response, body, jar } = await upstream("/holds", { method: "DELETE" });
    return withToken(body as Record<string, unknown>, jar, response.status);
  }

  const paths: Record<Exclude<Action, "release">, string> = {
    hold: `/events/${slug}/hold`,
    "best-available": `/events/${slug}/best-available`,
    checkout: `/events/${slug}/checkout`,
  };

  const path = paths[action as Exclude<Action, "release">];
  if (!path) {
    return NextResponse.json(
      { code: "VALIDATION_ERROR", message: "Unknown action." },
      { status: 400 },
    );
  }

  const { response, body, jar } = await upstream(path, {
    method: "POST",
    body: JSON.stringify(rest),
  });
  return withToken(body as Record<string, unknown>, jar, response.status);
}

/** Seat-level detail for one sector, fetched when a supporter drills in. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const slug = url.searchParams.get("slug");
  const sectionId = url.searchParams.get("section_id");

  if (!slug || !sectionId) {
    return NextResponse.json(
      { code: "VALIDATION_ERROR", message: "Missing match or sector." },
      { status: 400 },
    );
  }

  const { response, body } = await upstream(
    `/events/${slug}/seats?section_id=${encodeURIComponent(sectionId)}`,
  );
  return NextResponse.json(body, { status: response.status });
}
