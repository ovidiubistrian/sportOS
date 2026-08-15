import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense, type ReactNode } from "react";

import { siteTranslator, preferredLocale } from "@/lib/i18n";
import { getSite, paletteToStyle } from "@/lib/site";
import { Beacon } from "@/templates/beacon";
import { templateFor } from "@/templates";
import "../globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const site = await getSite();
  if (!site) return { title: "Not found" };
  return {
    title: { default: site.name, template: `%s · ${site.name}` },
    description: site.branding.tagline ?? `The official website of ${site.name}.`,
    openGraph: { title: site.name, siteName: site.name, type: "website" },
    robots: { index: true, follow: true },
  };
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const site = await getSite();
  // An unknown host is a 404, never a fallback club: serving one club's site on
  // another club's domain is the worst failure this app could have.
  if (!site) notFound();

  const { Shell } = templateFor(site.branding.template);
  const t = await siteTranslator(site);
  const lang = await preferredLocale(site);
  const mode = site.branding.color_mode.toLowerCase();

  return (
    <html
      lang={lang}
      data-mode={mode === "auto" ? undefined : mode}
      data-template={site.branding.template}
      // Brand tokens are injected per request. No per-tenant build, and no
      // flash of the wrong palette on first paint.
      style={paletteToStyle(site.branding)}
      suppressHydrationWarning
    >
      <body>
        <Shell site={site} i18n={t}>
          {children}
        </Shell>
        {/* Last in the tree and rendering nothing: measurement must never be
            in the way of the page it measures. */}
        <Suspense fallback={null}>
          <Beacon locale={lang} />
        </Suspense>
      </body>
    </html>
  );
}
