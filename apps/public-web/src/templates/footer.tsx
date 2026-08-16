import Link from "next/link";

import type { Site } from "@/lib/site";

import { Crest } from "./shared";

/**
 * The club's footer.
 *
 * Composed here rather than per template for the same reason the front page is:
 * the four templates disagree about layout, never about what a club puts at the
 * bottom of its website. What they *do* still own is their own chrome, so the
 * shell decides the surface this sits on and this decides what goes in it.
 *
 * Every part is optional and every part is off until the club fills it in. A
 * village club with a phone number gets a phone number; a Liga II club with a
 * registered address, four sponsors and a VAT line gets all four. Neither is
 * shown an empty heading for the things it does not have — an "Address" label
 * over nothing reads as a broken page, not as an invitation.
 */

export interface FooterLabels {
  contact: string;
  address: string;
  follow: string;
  sponsors: string;
  staffSignIn: string;
  account: string;
}

/** Only the networks the club actually filled in, in a fixed order. */
const NETWORKS = ["facebook", "instagram", "youtube", "tiktok", "x", "twitter"] as const;

function socialLinks(social: Record<string, string> | undefined) {
  if (!social) return [];
  return NETWORKS.filter((key) => social[key]).map((key) => ({
    key,
    // Capitalised for display; the key is the vocabulary, not the label.
    label: key === "x" ? "X" : key[0]!.toUpperCase() + key.slice(1),
    href: social[key]!,
  }));
}

export function SiteFooter({
  site,
  labels,
  inverted = false,
}: {
  site: Site;
  labels: FooterLabels;
  /** On a dark surface, where the rules and muted text invert. */
  inverted?: boolean;
}) {
  const { branding } = site;
  const social = socialLinks(branding.social as Record<string, string>);
  const sponsors = branding.sponsors ?? [];

  // Mixed from the text colour rather than from the brand, so one footer works
  // on a club-coloured surface and on the neutral dark one alike.
  const rule = inverted ? "color-mix(in srgb, currentColor 20%, transparent)" : "var(--rule)";
  const quiet = inverted ? "opacity-70" : "text-ink-muted";
  const faint = inverted ? "opacity-55" : "text-ink-faint";

  return (
    <div className="mx-auto max-w-6xl px-6">
      <div className="grid gap-10 py-12 sm:grid-cols-2 lg:grid-cols-4">
        <div className="lg:col-span-1">
          <Crest site={site} size={40} inverted={inverted} />
          <p className="font-display mt-4 text-base font-bold tracking-tight">{site.name}</p>
          {branding.tagline && (
            <p className={`mt-1 text-sm ${quiet}`}>{branding.tagline}</p>
          )}
        </div>

        {(branding.contact_email || branding.contact_phone) && (
          <div>
            <p className={`text-[11px] font-bold tracking-[0.18em] uppercase ${faint}`}>
              {labels.contact}
            </p>
            <ul className="mt-3 space-y-1.5 text-sm">
              {branding.contact_email && (
                <li>
                  <a
                    href={`mailto:${branding.contact_email}`}
                    className="underline-offset-4 hover:underline"
                  >
                    {branding.contact_email}
                  </a>
                </li>
              )}
              {branding.contact_phone && (
                <li>
                  <a
                    href={`tel:${branding.contact_phone.replace(/\s+/g, "")}`}
                    className="underline-offset-4 hover:underline"
                  >
                    {branding.contact_phone}
                  </a>
                </li>
              )}
            </ul>
          </div>
        )}

        {branding.address && (
          <div>
            <p className={`text-[11px] font-bold tracking-[0.18em] uppercase ${faint}`}>
              {labels.address}
            </p>
            {/* The club's own line breaks, kept: an address is a local format
                and reflowing one into a paragraph makes it wrong. */}
            <p className={`mt-3 text-sm whitespace-pre-line ${quiet}`}>{branding.address}</p>
          </div>
        )}

        {social.length > 0 && (
          <div>
            <p className={`text-[11px] font-bold tracking-[0.18em] uppercase ${faint}`}>
              {labels.follow}
            </p>
            <ul className="mt-3 space-y-1.5 text-sm">
              {social.map((link) => (
                <li key={link.key}>
                  <a
                    href={link.href}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="underline-offset-4 hover:underline"
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {sponsors.length > 0 && (
        <div className="border-t py-8" style={{ borderColor: rule }}>
          <p className={`text-[11px] font-bold tracking-[0.18em] uppercase ${faint}`}>
            {branding.sponsors_title ?? labels.sponsors}
          </p>
          {/* Logos on a light plate whatever the footer's colour: sponsor
              artwork is supplied for white and dies on a dark brand ground. */}
          <ul className="mt-4 flex flex-wrap items-center gap-3">
            {sponsors.map((sponsor) => {
              const body = sponsor.logo_url ? (
                <img
                  src={sponsor.logo_url}
                  alt={sponsor.name}
                  loading="lazy"
                  className="max-h-9 w-auto object-contain"
                />
              ) : (
                <span className="text-sm font-semibold">{sponsor.name}</span>
              );
              return (
                <li key={sponsor.name}>
                  {sponsor.url ? (
                    <a
                      href={sponsor.url}
                      target="_blank"
                      rel="noreferrer noopener sponsored"
                      className="inline-flex items-center rounded-lg bg-white px-4 py-2.5 text-ink transition-opacity hover:opacity-85"
                    >
                      {body}
                    </a>
                  ) : (
                    <span className="inline-flex items-center rounded-lg bg-white px-4 py-2.5 text-ink">
                      {body}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div
        className="flex flex-col gap-3 border-t py-6 text-xs sm:flex-row sm:items-center sm:justify-between"
        style={{ borderColor: rule }}
      >
        <p className={faint}>
          © {new Date().getFullYear()} {site.name}
          {branding.legal_line ? ` · ${branding.legal_line}` : ""}
        </p>
        <span className="flex items-center gap-4">
          <Link href="/cont" className={`underline-offset-4 hover:underline ${faint}`}>
            {labels.account}
          </Link>
          <a
            href={process.env.NEXT_PUBLIC_ADMIN_URL ?? "http://footbola.localhost/signin"}
            className={`underline-offset-4 hover:underline ${faint}`}
          >
            {labels.staffSignIn}
          </a>
        </span>
      </div>
    </div>
  );
}
