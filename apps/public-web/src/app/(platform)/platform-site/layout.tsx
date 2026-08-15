import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Footer, Header } from "./chrome";
import "../../globals.css";
import "./marketing.css";

/**
 * The platform's own site.
 *
 * A separate root layout from the club sites, not a variant of one. The two
 * products share a deployment and nothing else: this one has fixed branding,
 * its own palette and its own chrome, and it must never inherit a club's
 * colours or be reachable from a club's domain.
 */

export const metadata: Metadata = {
  title: {
    default: "TeamSport360 — one place to run the club",
    template: "%s · TeamSport360",
  },
  description:
    "Squads, academy, matchday, the club website and the money — one system, "
    + "built for clubs that run on volunteers and spreadsheets.",
  openGraph: {
    title: "TeamSport360",
    siteName: "TeamSport360",
    type: "website",
  },
  robots: { index: true, follow: true },
};

export default function PlatformLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="marketing">
      <body>
        <Header />
        <main>{children}</main>
        <Footer />
      </body>
    </html>
  );
}
