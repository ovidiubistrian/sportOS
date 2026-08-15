import { NextResponse, type NextRequest } from "next/server";

/**
 * Host-based routing.
 *
 * One deployment serves two different products from the same Next.js app:
 *
 *   `footbola.localhost`  the platform's own marketing site
 *   anything else         a club's website, resolved from the Host header
 *
 * Doing the split here rather than in each page keeps every club page free of
 * "…unless this is the platform host" branches, and — more importantly — makes
 * the guard total. The marketing segment is rewritten *into* on the platform
 * host and rewritten *away from* everywhere else, so a club's domain can never
 * serve the platform's pricing page, and the platform host can never serve a
 * club's content.
 */

const PLATFORM_HOST = (process.env.NEXT_PUBLIC_PLATFORM_HOST ?? "footbola.localhost")
  .split(":")[0]!
  .toLowerCase();

const MARKETING_ROOT = "/platform-site";

function hostOf(request: NextRequest): string {
  // X-Forwarded-Host is set by the proxy; Host is the fallback for direct hits.
  const raw =
    request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? "";
  return raw.split(",")[0]!.trim().split(":")[0]!.toLowerCase();
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const host = hostOf(request);

  if (host === PLATFORM_HOST) {
    if (pathname.startsWith(MARKETING_ROOT)) return NextResponse.next();
    const target = pathname === "/" ? MARKETING_ROOT : `${MARKETING_ROOT}${pathname}`;
    return NextResponse.rewrite(new URL(`${target}${search}`, request.url));
  }

  // A club domain must never serve the platform's marketing pages, even if
  // someone types the internal path directly.
  if (pathname.startsWith(MARKETING_ROOT)) {
    return NextResponse.rewrite(new URL("/404", request.url));
  }

  return NextResponse.next();
}

export const config = {
  // Everything except Next's own assets and the revalidation endpoint.
  matcher: ["/((?!_next/static|_next/image|api/|favicon.ico).*)"],
};
