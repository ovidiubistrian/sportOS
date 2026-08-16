import { notFound } from "next/navigation";

import { preferredLocale, siteTranslator } from "@/lib/i18n";
import { getHistory, getMatches, getNews, getSite, getTable } from "@/lib/site";
import { MatchCalendar } from "@/templates/calendar";
import { NewsCarousel } from "@/templates/carousel";
import { ClubFeed } from "@/templates/club-feed";
import { MatchTimeline } from "@/templates/events";
import { ClubRecord } from "@/templates/history";
import { Newsletter } from "@/templates/newsletter";
import { OpeningHero } from "@/templates/opening";
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

  const [i18n, locale, articles, matches, table, history] = await Promise.all([
    siteTranslator(site),
    preferredLocale(site),
    getNews(14),
    getMatches(true, 5),
    getTable(),
    getHistory(),
  ]);

  // The hero takes the newest few; the feed takes what is left, so the same
  // story is not the first thing a visitor sees twice.
  const hero = articles.slice(0, 4);
  const feed = articles.slice(4);

  return (
    <>
      {/* The carousel renders nothing without articles, which on a club's
          first day left the page opening at the newsletter signup — just after
          they had uploaded something called the home page image. */}
      {hero.length === 0 && <OpeningHero site={site} />}
      <NewsCarousel
        site={site}
        articles={hero}
        labels={{
          news: i18n.t("publicSite", "news"),
          readMore: i18n.t("publicSite", "readMore"),
          previous: i18n.t("publicSite", "previous"),
          next: i18n.t("publicSite", "next"),
        }}
      />
      <FeaturedMatch site={site} match={matches[0]} i18n={i18n} locale={locale} />
      {matches[0] && (
        <MatchTimeline
          match={matches[0]}
          title={i18n.t("publicSite", "events")}
          labels={{
            goal: i18n.t("publicSite", "goal"),
            ownGoal: i18n.t("publicSite", "ownGoal"),
            penalty: i18n.t("publicSite", "penalty"),
            missedPenalty: i18n.t("publicSite", "missedPenalty"),
            yellow: i18n.t("publicSite", "yellowCard"),
            red: i18n.t("publicSite", "redCard"),
            substitution: i18n.t("publicSite", "substitution"),
          }}
        />
      )}
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
          tbc: i18n.t("publicSite", "kickoffTbc"),
          matchday: i18n.t("publicSite", "matchday"),
        }}
      />
      <LeagueTable rows={table} i18n={i18n} scoringUnit={site.scoring_unit} />

      {/* Everything the club has to say that is not a fixture. Skips whatever
          is already the hero above, so the same story is not the first thing
          twice. */}
      <ClubFeed
        site={site}
        articles={feed}
        labels={{
          title: i18n.t("publicSite", "clubFeed"),
          subtitle: i18n.t("publicSite", "clubFeedHint"),
          readMore: i18n.t("publicSite", "readMore"),
          previous: i18n.t("publicSite", "previous"),
          next: i18n.t("publicSite", "next"),
          types: {
            ANNOUNCEMENT: i18n.t("publicSite", "typeANNOUNCEMENT"),
            MATCH_REPORT: i18n.t("publicSite", "typeMATCH_REPORT"),
            MATCH_PREVIEW: i18n.t("publicSite", "typeMATCH_PREVIEW"),
            SIGNING: i18n.t("publicSite", "typeSIGNING"),
            DEPARTURE: i18n.t("publicSite", "typeDEPARTURE"),
            ACADEMY: i18n.t("publicSite", "typeACADEMY"),
            INTERVIEW: i18n.t("publicSite", "typeINTERVIEW"),
          },
        }}
      />

      {/* The club's record, last before the footer: it is what a supporter
          reads when they have finished with this week and want the longer
          story. */}
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

      <Newsletter
        labels={{
          title: i18n.t("publicSite", "newsletterTitle"),
          body: i18n.t("publicSite", "newsletterBody"),
          placeholder: i18n.t("publicSite", "newsletterEmail"),
          submit: i18n.t("publicSite", "newsletterSubmit"),
          done: i18n.t("publicSite", "newsletterDone"),
          failed: i18n.t("publicSite", "newsletterFailed"),
          consent: i18n.t("publicSite", "newsletterConsent"),
        }}
      />
    </>
  );
}
