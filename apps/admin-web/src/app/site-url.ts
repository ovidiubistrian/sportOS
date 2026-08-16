/**
 * Where a club's own website lives.
 *
 * A club gets `<slug>.<platform domain>`: a subdomain, because the public site
 * decides which club a request belongs to from the Host header alone, and
 * because it is the same shape a club gets when it brings its own domain.
 *
 * The domain is fixed at build time — Vite resolves `import.meta.env` while
 * compiling, so the admin bundle is built for the domain it will be served
 * from and cannot be told a different one afterwards.
 *
 * This existed as `` `http://${club.slug}.localhost` `` in six separate
 * components, which is how a production deployment ended up with a "View site"
 * button pointing at the developer's machine.
 */

export const PLATFORM_DOMAIN =
  (import.meta.env.VITE_PUBLIC_SITE_DOMAIN as string | undefined)?.trim() ||
  "footbola.localhost";

/** `csm-resita.teamsport360.com` — what to show when naming the address. */
export function clubHostname(slug: string): string {
  return `${slug}.${PLATFORM_DOMAIN}`;
}

/**
 * The full URL to open.
 *
 * Plain HTTP only for `.localhost`, where there is no certificate and never
 * will be. Everywhere else a club site is HTTPS from its first visit — the
 * certificate is issued on demand, so linking to `http://` would cost a
 * redirect on every click.
 */
export function clubSiteUrl(slug: string): string {
  const host = clubHostname(slug);
  const scheme = PLATFORM_DOMAIN.endsWith("localhost") ? "http" : "https";
  return `${scheme}://${host}`;
}
