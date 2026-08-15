import { notFound } from "next/navigation";

import { preferredLocale, siteTranslator } from "@/lib/i18n";
import { getHistory, getSite } from "@/lib/site";
import { ClubRecord } from "@/templates/history";
import { SectionHeading } from "@/templates/section";

export const metadata = { title: "Club" };

/**
 * The club page: who they are, and what they have done.
 *
 * The record below the facts is the part supporters come for — where the club
 * finished each season, and anything it has won. Both are pulled from the
 * league feed when one is connected, so a club that has not connected sees the
 * facts alone rather than an empty table.
 */
export default async function ClubPage() {
  const site = await getSite();
  if (!site) notFound();

  const [i18n, locale, history] = await Promise.all([
    siteTranslator(site),
    preferredLocale(site),
    getHistory(),
  ]);

  return (
    <main>
      <section className="mx-auto max-w-6xl px-6 pt-14">
        <SectionHeading
          eyebrow={i18n.t("publicSite", "theClub")}
          title={site.name}
          lead={site.branding.tagline ?? undefined}
        />
      </section>

      {history && (
        <ClubRecord
          history={history}
          locale={locale}
          labels={{
            title: i18n.t("publicSite", "history"),
            lead: i18n.t("publicSite", "historyLead"),
            season: i18n.t("publicSite", "seasonCol"),
            competition: i18n.t("publicSite", "competitionCol"),
            position: i18n.t("publicSite", "positionCol"),
            played: i18n.t("publicSite", "playedCol"),
            record: i18n.t("publicSite", "recordCol"),
            points: i18n.t("publicSite", "points"),
            honours: i18n.t("publicSite", "honours"),
            founded: i18n.t("publicSite", "founded"),
            ground: i18n.t("publicSite", "ground"),
            capacity: i18n.t("publicSite", "capacity"),
          }}
        />
      )}
    </main>
  );
}
