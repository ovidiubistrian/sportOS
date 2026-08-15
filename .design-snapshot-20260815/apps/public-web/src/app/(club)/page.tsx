import { notFound } from "next/navigation";

import { preferredLocale, siteTranslator } from "@/lib/i18n";
import { getMatches, getNews, getSite, getTable } from "@/lib/site";
import { MatchCalendar } from "@/templates/calendar";
import { NewsCarousel } from "@/templates/carousel";
import { FeaturedMatch, LeagueTable } from "@/templates/matchday";

/**
 * The club's front page.
 *
 * Composed here rather than in the templates, because the order is the club's
 * reading of its own week and does not change with the design: the club's own
 * news, then the next fixture as a slim bar under it, then the rest of the run
 * and where that leaves us in the table.
 *
 * The fixture is the question most people arrive with, which is why it sits
 * directly under the hero rather than further down — but it is one line of
 * fact, and at hero size it pushed the club's own news into second place.
 *
 * The squad list lives on /teams: it is a reference page, and a supporter
 * checking a kick-off time should not scroll past six age groups to find it.
 */
export default async function HomePage() {
  const site = await getSite();
  if (!site) notFound();

  const [i18n, locale, articles, matches, table] = await Promise.all([
    siteTranslator(site),
    preferredLocale(site),
    getNews(5),
    getMatches(true, 5),
    getTable(),
  ]);

  return (
    <>
      <NewsCarousel
        site={site}
        articles={articles}
        labels={{
          news: i18n.t("publicSite", "news"),
          readMore: i18n.t("publicSite", "readMore"),
          previous: i18n.t("publicSite", "previous"),
          next: i18n.t("publicSite", "next"),
        }}
      />
      <FeaturedMatch site={site} match={matches[0]} i18n={i18n} locale={locale} />
      {/* The whole run, including the one in the bar above — a calendar that
          starts at the second fixture is not a calendar. */}
      <MatchCalendar
        site={site}
        matches={matches}
        locale={locale}
        labels={{
          calendar: i18n.t("publicSite", "calendar"),
          nextMatch: i18n.t("publicSite", "nextMatch"),
          days: i18n.t("publicSite", "days"),
          hours: i18n.t("publicSite", "hours"),
          minutes: i18n.t("publicSite", "minutes"),
          seconds: i18n.t("publicSite", "secondsShort"),
          buyTickets: i18n.t("publicSite", "buyTickets"),
          fullCalendar: i18n.t("publicSite", "fullCalendar"),
        }}
      />
      <LeagueTable rows={table} i18n={i18n} />
    </>
  );
}
