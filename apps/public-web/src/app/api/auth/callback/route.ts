import { NextResponse } from "next/server";

import { completeSignIn, keep, origin } from "@/lib/auth";

/**
 * Back from Keycloak.
 *
 * The session cookies are written onto the redirect itself. Writing them
 * through `cookies()` instead left a gap where the browser followed the
 * redirect before the cookies were applied — sign in, arrive as a stranger,
 * refresh, and suddenly be signed in.
 *
 * A failure here — a mismatched state, a stale request, a refused exchange —
 * lands the visitor back on the club's front page rather than on an error
 * screen. There is nothing they could do about it, and the club's site is a
 * better place to be than a stack trace.
 */
export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const code = params.get("code");
  const state = params.get("state");
  const home = await origin();

  if (!code || !state) return NextResponse.redirect(home, { status: 302 });

  const result = await completeSignIn(code, state);
  if (!result) return NextResponse.redirect(home, { status: 302 });

  return keep(
    NextResponse.redirect(`${home}${result.next}`, { status: 302 }),
    result.tokens,
  );
}
