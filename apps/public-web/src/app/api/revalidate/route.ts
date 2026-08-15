import { revalidatePath, revalidateTag } from "next/cache";
import { NextResponse } from "next/server";

/**
 * On-demand cache purge.
 *
 * Called by the API when a club changes its design, so the change is visible
 * immediately rather than at the end of the ISR window. Internal network only,
 * guarded by a shared secret — it takes no user input beyond a hostname and can
 * only ever discard a cache entry, never read or write club data.
 */

const SECRET = process.env.REVALIDATE_SECRET ?? "dev-only-revalidate-secret";

function constantTimeEquals(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let mismatch = 0;
  for (let index = 0; index < a.length; index += 1) {
    mismatch |= a.charCodeAt(index) ^ b.charCodeAt(index);
  }
  return mismatch === 0;
}

export async function POST(request: Request) {
  const provided = request.headers.get("x-revalidate-secret") ?? "";
  if (!constantTimeEquals(provided, SECRET)) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  const body = (await request.json().catch(() => null)) as { host?: string } | null;
  const host = body?.host?.trim().toLowerCase();
  if (!host) {
    return NextResponse.json({ error: "host is required" }, { status: 400 });
  }

  // Matches the tag every public fetch is registered under in lib/site.ts.
  revalidateTag(`site:${host}`);

  // The tag clears the *data* cache; the rendered routes are cached separately
  // and would keep serving the old HTML until their own window expired. That
  // is why changing a template appeared to do nothing: the new template was
  // fetched and the old page was still served. "layout" covers every route
  // under it, which is what a design change touches.
  revalidatePath("/", "layout");

  return NextResponse.json({ revalidated: host });
}
