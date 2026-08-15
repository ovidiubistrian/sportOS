import { cookies, headers } from "next/headers";
import type { NextResponse } from "next/server";

/**
 * Supporter sign-in.
 *
 * A supporter signs in with the same platform login everywhere, but arrives at
 * a club's own address — so the browser is sent to Keycloak with a redirect
 * back to *this* club's domain, and the account it lands in is decided by that
 * domain and nothing else.
 *
 * Authorization code with PKCE, and the code-for-token exchange happens here on
 * the server, over the internal network. The browser never holds an access
 * token: both tokens live in httpOnly cookies, which is what makes a script on
 * the page — the club's own analytics, an embedded widget — unable to lift a
 * supporter's session.
 *
 * Two issuers is not a mistake. The browser must be sent somewhere it can
 * actually reach (`auth.footbola.localhost`), while the server talks to
 * Keycloak directly (`keycloak:8080`); a single value would either break the
 * redirect or route server traffic out through the proxy.
 */

const PUBLIC_ISSUER =
  process.env.OIDC_PUBLIC_ISSUER ?? "http://auth.footbola.localhost/realms/football-os";
const INTERNAL_ISSUER =
  process.env.OIDC_ISSUER ?? "http://keycloak:8080/realms/football-os";
const CLIENT_ID = process.env.SUPPORTER_CLIENT_ID ?? "supporter-web";

export const ACCESS_COOKIE = "fos_at";
export const REFRESH_COOKIE = "fos_rt";
const VERIFIER_COOKIE = "fos_pkce";
const STATE_COOKIE = "fos_state";

/** Cookies are per host, which is what keeps two clubs' sessions apart. */
const BASE = { httpOnly: true, sameSite: "lax", path: "/", secure: false } as const;

export interface TokenSet {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
}

function base64url(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("base64url");
}

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

/** The address this club is being read on, scheme included. */
export async function origin(): Promise<string> {
  const incoming = await headers();
  const host = incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "localhost";
  const proto = incoming.get("x-forwarded-proto") ?? "http";
  return `${proto}://${host}`;
}

export async function currentHost(): Promise<string> {
  const incoming = await headers();
  return incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "localhost";
}

/**
 * Where to send the browser to sign in.
 *
 * `next` is kept in a cookie rather than in the state parameter: state is for
 * proving the response belongs to this request, and stuffing a destination
 * into it invites somebody to try an open redirect through it.
 */
export async function beginSignIn(
  response: NextResponse,
  next: string,
  register = false,
): Promise<string> {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const state = base64url(crypto.getRandomValues(new Uint8Array(16)));

  // On the response for the same reason the session cookies are: this handler
  // returns its own redirect, and a verifier that never reaches the browser
  // makes the callback fail the state check and drop the visitor home.
  response.cookies.set(VERIFIER_COOKIE, verifier, { ...BASE, maxAge: 600 });
  response.cookies.set(STATE_COOKIE, `${state}|${safeNext(next)}`, {
    ...BASE,
    maxAge: 600,
  });

  const url = new URL(
    // Keycloak's registration page is the same flow with a different first
    // screen, so "create an account" is one parameter, not a second stack.
    `${PUBLIC_ISSUER}/protocol/openid-connect/${register ? "registrations" : "auth"}`,
  );
  url.searchParams.set("client_id", CLIENT_ID);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid profile email");
  url.searchParams.set("redirect_uri", `${await origin()}/api/auth/callback`);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", await challengeFor(verifier));
  url.searchParams.set("code_challenge_method", "S256");
  return url.toString();
}

/** Only ever come back to a path on this site. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return "/cont";
  return next;
}

export async function completeSignIn(
  code: string,
  state: string,
): Promise<{ tokens: TokenSet; next: string } | null> {
  const jar = await cookies();
  const verifier = jar.get(VERIFIER_COOKIE)?.value;
  const stored = jar.get(STATE_COOKIE)?.value;
  jar.delete(VERIFIER_COOKIE);
  jar.delete(STATE_COOKIE);

  if (!verifier || !stored) return null;
  const [expected, next] = stored.split("|");
  if (!expected || expected !== state) return null;

  const response = await fetch(`${INTERNAL_ISSUER}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: CLIENT_ID,
      code,
      code_verifier: verifier,
      redirect_uri: `${await origin()}/api/auth/callback`,
    }),
    cache: "no-store",
  });
  if (!response.ok) return null;

  return { tokens: (await response.json()) as TokenSet, next: safeNext(next) };
}

export async function refresh(): Promise<TokenSet | null> {
  const token = (await cookies()).get(REFRESH_COOKIE)?.value;
  if (!token) return null;

  const response = await fetch(`${INTERNAL_ISSUER}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      client_id: CLIENT_ID,
      refresh_token: token,
    }),
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as TokenSet;
}

/**
 * Hold the session, by writing the cookies onto the response itself.
 *
 * Deliberately not `cookies().set()` from `next/headers`. That mutates a jar
 * the framework attaches to *its own* response, and a handler that builds its
 * own `NextResponse` — every redirect here does — can return before the jar is
 * applied. The symptom is precisely the one this had: sign in, land on the
 * account page as a stranger, press refresh, and suddenly be signed in.
 *
 * Setting them on the response that is actually returned has no such gap.
 */
export function keep(response: NextResponse, tokens: TokenSet): NextResponse {
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    ...BASE,
    // A minute short of the real expiry, so a request that starts just under
    // the wire does not finish just over it.
    maxAge: Math.max(30, tokens.expires_in - 60),
  });
  if (tokens.refresh_token) {
    response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
      ...BASE,
      maxAge: 60 * 60 * 24 * 30,
    });
  }
  return response;
}

export function forget(response: NextResponse): NextResponse {
  // Set to empty with a zero lifetime rather than deleted: an expired cookie
  // is what actually removes it from a browser that already holds one.
  response.cookies.set(ACCESS_COOKIE, "", { ...BASE, maxAge: 0 });
  response.cookies.set(REFRESH_COOKIE, "", { ...BASE, maxAge: 0 });
  return response;
}

/** Where to send the browser to end the Keycloak session as well as ours. */
export async function endSessionUrl(idHint?: string): Promise<string> {
  const url = new URL(`${PUBLIC_ISSUER}/protocol/openid-connect/logout`);
  url.searchParams.set("client_id", CLIENT_ID);
  url.searchParams.set("post_logout_redirect_uri", `${await origin()}/`);
  if (idHint) url.searchParams.set("id_token_hint", idHint);
  return url.toString();
}
