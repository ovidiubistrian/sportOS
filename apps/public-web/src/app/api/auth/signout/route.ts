import { NextResponse } from "next/server";

import { endSessionUrl, forget } from "@/lib/auth";

/**
 * Sign out here, and at Keycloak.
 *
 * POST, not GET: a link that a page can be made to prefetch must not be able
 * to end somebody's session. The club's own cookies are dropped first, so even
 * if the round trip to Keycloak fails the supporter is signed out of this site.
 */
export async function POST() {
  return forget(NextResponse.redirect(await endSessionUrl(), { status: 303 }));
}
