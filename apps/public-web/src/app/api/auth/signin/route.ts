import { NextResponse } from "next/server";

import { beginSignIn, safeNext } from "@/lib/auth";

/**
 * Start a sign-in.
 *
 * `?register=1` opens Keycloak's create-account screen instead of its sign-in
 * one — same flow, same client, one fewer click for somebody who has never
 * bought anything from this club before.
 *
 * The redirect is built first so the PKCE cookies can be written onto it. They
 * have to reach the browser before it leaves, or the callback has nothing to
 * verify the response against.
 */
export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;

  // A placeholder location, replaced once the authorization URL is built.
  const response = NextResponse.redirect(new URL("/", request.url), { status: 302 });
  const url = await beginSignIn(
    response,
    safeNext(params.get("next")),
    params.get("register") === "1",
  );

  return NextResponse.redirect(url, { status: 302, headers: response.headers });
}
