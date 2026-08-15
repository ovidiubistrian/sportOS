import { NextResponse } from "next/server";

import { forget, keep, origin, refresh, safeNext } from "@/lib/auth";

/**
 * Renew the short-lived half of the session.
 *
 * Pages redirect here when their access token has expired, because a server
 * component cannot write a cookie and this can. A refusal clears both cookies
 * and sends the visitor on anyway: they then read the page as a signed-out
 * visitor, which is the truth, and no loop forms because there is no longer a
 * refresh token to try.
 */
export async function GET(request: Request) {
  const next = safeNext(new URL(request.url).searchParams.get("next"));
  const home = await origin();

  const tokens = await refresh();
  const response = NextResponse.redirect(`${home}${next}`, { status: 302 });
  return tokens ? keep(response, tokens) : forget(response);
}
