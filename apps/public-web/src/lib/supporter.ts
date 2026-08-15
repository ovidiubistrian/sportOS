import { cookies } from "next/headers";

import { ACCESS_COOKIE, REFRESH_COOKIE, currentHost } from "./auth";

/**
 * The signed-in supporter, as a page sees them.
 *
 * Reading is done here; renewing is not. A server component cannot write a
 * cookie, so when the access token has expired this returns `"expired"` and the
 * page redirects through `/api/auth/refresh` — a route handler, which can. It
 * is one extra hop every few minutes in exchange for never holding a token
 * where a script could read it.
 */

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

export interface Supporter {
  display_name: string;
  email: string | null;
  phone: string | null;
  marketing_opt_in: boolean;
}

export interface SupporterOrderLine {
  description: string;
  quantity: number;
  total_minor: number;
}

export interface SupporterOrder {
  reference: string;
  status: string;
  currency: string;
  total_minor: number;
  placed_at: string | null;
  collected_at: string | null;
  lines: SupporterOrderLine[];
}

export type Session<T> = { state: "anonymous" } | { state: "expired" } | { state: "ok"; data: T };

async function call<T>(path: string): Promise<Session<T>> {
  const jar = await cookies();
  const token = jar.get(ACCESS_COOKIE)?.value;

  if (!token) {
    // No access token but a refresh token means the session is alive and only
    // the short-lived half lapsed — worth a renewal, unlike a visitor who has
    // never signed in.
    return jar.get(REFRESH_COOKIE) ? { state: "expired" } : { state: "anonymous" };
  }

  const response = await fetch(`${API}/api/v1/public/account${path}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      "X-Forwarded-Host": await currentHost(),
    },
    cache: "no-store",
  });

  // A token we *have* being refused is not something renewing fixes — the
  // cookie is written to die a minute before the token does, so this is a
  // genuinely bad session, not a lapsed one. Treating it as expired here is
  // what turns one bad token into an endless refresh loop.
  if (response.status === 401) return { state: "anonymous" };
  if (!response.ok) return { state: "anonymous" };
  return { state: "ok", data: (await response.json()) as T };
}

export function getSupporter(): Promise<Session<Supporter>> {
  return call<Supporter>("");
}

export function getSupporterOrders(): Promise<Session<SupporterOrder[]>> {
  return call<SupporterOrder[]>("/orders");
}

/** Is anybody signed in at all? Cheap enough for the header on every page. */
export async function isSignedIn(): Promise<boolean> {
  const jar = await cookies();
  return Boolean(jar.get(ACCESS_COOKIE) ?? jar.get(REFRESH_COOKIE));
}
