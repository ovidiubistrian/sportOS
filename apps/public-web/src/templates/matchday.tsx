import type { Translator } from "@footbola/i18n";

import { roundLabel } from "@/lib/round";
import { Scorers } from "./events";
import type { PublicMatch, PublicTableRow, Site } from "@/lib/site";
import { SectionHeading } from "./section";

/**
 * The matchday blocks: what a club puts under its hero.
 *
 * Shared by every template rather than written four times. The four differ in
 * how a page is *composed* — a hero, a masthead, a column width — not in what a
 * fixture is, and a fixture rendered four slightly different ways is four
 * places for the kick-off time to be wrong.
 *
 * Colour comes from the club's tokens, so these blocks arrive already in the
 * club's own red or green without any template passing a palette down.
 */

function Crest({
  club,
  size = 28,
  className,
}: {
  club: { name: string; crest_url: string | null };
  size?: number;
  /** Sizing classes, for a crest that has to change with the viewport. The
   *  inline style steps aside when this is given — it would win otherwise. */
  className?: string;
}) {
  if (!club.crest_url) return null;
  return (
    <img
      src={club.crest_url}
      alt=""
      // Kept whatever sizes it: the intrinsic ratio is what stops the row
      // jumping as crests arrive.
      width={size}
      height={size}
      className={`shrink-0 object-contain ${className ?? ""}`}
      style={className ? undefined : { width: size, height: size }}
    />
  );
}

function kickoff(match: PublicMatch, site: Site, locale: string): string {
  if (!match.kickoff_at) return "—";
  const date = new Date(match.kickoff_at);
  const day = new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: site.timezone,
  }).format(date);

  // An unconfirmed kick-off shows the day and says so, rather than inventing a
  // time the club has not been given.
  if (!match.kickoff_is_confirmed) return day;

  const time = new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: site.timezone,
  }).format(date);
  return `${day} · ${time}`;
}

/* --- the next match -------------------------------------------------------- */

export function FeaturedMatch({
  site,
  match,
  i18n,
  locale,
}: {
  site: Site;
  match: PublicMatch | undefined;
  i18n: Translator;
  locale: string;
}) {
  if (!match) return null;

  // The club's own link, home or away. Unlike the calendar cards — where a
  // per-fixture link means "tickets for this match" — this band is the club's
  // standing invitation, and it should be there whoever is hosting.
  const ticketUrl = match.ticket_url ?? site.branding.tickets_url;
  const live = match.status === "LIVE";

  return (
    /* A scoreboard, directly under the hero. Slim — one line of fact, not a
       screen of its own — but read as a scoreboard rather than a sentence,
       because that is the shape a supporter's eye already knows. */
    <section
      className="px-6 py-5"
      style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
    >
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-3">
        {live ? (
          <p className="flex items-center gap-2 font-display text-[10px] font-bold tracking-[0.2em] uppercase">
            {/* A dot that pulses, because "LIVE" in text alone reads as a
                label rather than as something happening now. */}
            <span className="relative flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
              <span className="relative inline-flex size-2 rounded-full bg-current" />
            </span>
            {i18n.t("publicSite", "liveNow")}
            {match.minute != null && <span className="opacity-70">{match.minute}&apos;</span>}
          </p>
        ) : (
          <p className="font-display text-[10px] font-bold tracking-[0.2em] uppercase opacity-70">
            {i18n.t("publicSite", "nextMatch")}
          </p>
        )}

        <div className="flex w-full items-center justify-center gap-5 sm:gap-10">
          <Side club={match.home} align="right" />

          <div className="shrink-0 text-center">
            <p className="tabular font-display text-3xl leading-none font-extrabold sm:text-4xl">
              {/* Before kick-off the scoreboard rests at nil-nil, which is
                  where every match starts. It becomes the real score the
                  moment the club records one. */}
              {match.home_score ?? 0}
              <span className="mx-2 opacity-50">–</span>
              {match.away_score ?? 0}
            </p>
            {!live && match.status === "SCHEDULED" && (
              <p className="tabular mt-1.5 text-[11px] tracking-wider uppercase opacity-70">
                {kickoffDay(match, site, locale)}
                {kickoffTime(match, site, locale)
                  ? ` · ${kickoffTime(match, site, locale)}`
                  : ""}
              </p>
            )}
          </div>

          <Side club={match.away} align="left" />
        </div>

        {/* Who scored, right under the score. The one thing a supporter
            checking a live game wants after the number itself. */}
        <Scorers match={match} />

        <p className="text-xs opacity-70">
          {[
            match.competition,
            roundLabel(match, i18n.t("publicSite", "matchday")),
            match.venue_name,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>

        {site.branding.announcement && (
          <p className="max-w-2xl text-center text-xs opacity-85">
            {site.branding.announcement}
          </p>
        )}

        {ticketUrl && (
          <a
            href={ticketUrl}
            className="mt-1 rounded-sm px-6 py-2.5 text-[11px] font-bold tracking-widest uppercase transition-opacity hover:opacity-90"
            style={{ background: "var(--brand-contrast)", color: "var(--brand)" }}
          >
            {site.branding.tickets_label || i18n.t("publicSite", "buyTickets")}
          </a>
        )}
      </div>
    </section>
  );
}

function Side({
  club,
  align,
}: {
  club: PublicMatch["home"];
  align: "left" | "right";
}) {
  return (
    // `min-w-0`, or the row cannot narrow past the two club names: a flex item
    // refuses to shrink below its content unless told it may, so on a phone
    // this band pushed the whole page wider than the screen rather than giving
    // way. The crest is smaller there too — at 72 points a pair of them plus a
    // score leaves nothing for the names.
    <div
      className={
        align === "right"
          ? "flex min-w-0 flex-1 items-center justify-end gap-2 sm:gap-3"
          : "flex min-w-0 flex-1 items-center gap-2 sm:gap-3"
      }
    >
      {align === "right" && <Name club={club} />}
      <Crest club={club} size={72} className="size-12 sm:size-[72px]" />
      {align === "left" && <Name club={club} />}
    </div>
  );
}

function Name({ club }: { club: PublicMatch["home"] }) {
  return (
    <>
      {/* The short name on a phone, the full one once there is room — the
          abbreviation is the club's own, set in Site & design. Truncated even
          so: a club whose "short" name is not short would otherwise widen the
          row past the screen, and a clipped name is better than a broken
          page. */}
      <span className="font-display truncate text-base font-extrabold tracking-tight sm:hidden">
        {club.short_name}
      </span>
      <span className="font-display hidden truncate text-lg font-extrabold tracking-tight sm:inline">
        {club.name}
      </span>
    </>
  );
}

function kickoffTime(match: PublicMatch, site: Site, locale: string): string | null {
  if (!match.kickoff_at || !match.kickoff_is_confirmed) return null;
  return new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: site.timezone,
  }).format(new Date(match.kickoff_at));
}

function kickoffDay(match: PublicMatch, site: Site, locale: string): string {
  if (!match.kickoff_at) return "";
  return new Intl.DateTimeFormat(locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: site.timezone,
  }).format(new Date(match.kickoff_at));
}

/* --- fixtures -------------------------------------------------------------- */

export function NextMatches({
  site,
  matches,
  i18n,
  locale,
}: {
  site: Site;
  matches: PublicMatch[];
  i18n: Translator;
  locale: string;
}) {
  if (matches.length === 0) return null;

  return (
    <section className="mx-auto max-w-5xl px-6 py-12">
      <h2 className="font-display mb-5 text-xs font-bold tracking-[0.2em] text-ink-muted uppercase">
        {i18n.t("publicSite", "nextMatches")}
      </h2>

      <ul className="divide-y divide-rule border-y border-rule">
        {matches.map((match) => (
          <li
            key={match.id}
            className="grid items-center gap-3 py-4 sm:grid-cols-[9rem_1fr_auto]"
          >
            <div className="text-xs text-ink-muted">
              <p className="tabular font-medium text-ink">{kickoff(match, site, locale)}</p>
              <p className="mt-0.5">
                {[match.competition, roundLabel(match, i18n.t("publicSite", "matchday"))]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>

            <div className="flex items-center gap-2.5 text-sm font-semibold">
              <Crest club={match.home} />
              <span className={match.is_home ? "" : "text-ink-muted"}>{match.home.name}</span>
              <span className="text-ink-faint">–</span>
              <Crest club={match.away} />
              <span className={match.is_home ? "text-ink-muted" : ""}>{match.away.name}</span>
            </div>

            <div className="flex items-center gap-3 sm:justify-end">
              {match.venue_name && (
                <span className="hidden text-xs text-ink-faint sm:inline">
                  {match.venue_name}
                </span>
              )}
              {match.ticket_url && (
                <a
                  href={match.ticket_url}
                  className="rounded-sm px-3 py-1.5 text-xs font-bold tracking-wider uppercase"
                  style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
                >
                  {i18n.t("publicSite", "buyTickets")}
                </a>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* --- the ticket call to action --------------------------------------------- */

export function TicketsCta({ site, i18n }: { site: Site; i18n: Translator }) {
  if (!site.branding.tickets_url) return null;
  return (
    <section className="px-6 py-14 text-center">
      <a
        href={site.branding.tickets_url}
        className="inline-block rounded-sm px-8 py-4 text-sm font-bold tracking-widest uppercase transition-opacity hover:opacity-90"
        style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
      >
        {site.branding.tickets_label || i18n.t("publicSite", "buyTickets")}
      </a>
    </section>
  );
}

/* --- table ----------------------------------------------------------------- */

export function LeagueTable({
  rows,
  i18n,
  scoringUnit = "GOAL",
}: {
  rows: PublicTableRow[];
  i18n: Translator;
  /**
   * What one unit of score is called here.
   *
   * A handball club's table says goal difference and a basketball club's says
   * points difference, and neither template knows anything about either sport
   * — the club's own profile supplies the word.
   */
  scoringUnit?: string;
}) {
  if (rows.length === 0) return null;

  const differenceLabel = i18n.t(
    "publicSite",
    `difference${scoringUnit}` as "differenceGOAL",
  );

  return (
    <section className="mx-auto max-w-6xl px-6 py-14">
      <SectionHeading title={i18n.t("publicSite", "standings")} />

      {/* Its own scroll container: a table is the one block that legitimately
          exceeds a phone's width, and the page body must never scroll sideways
          because of it. */}
      <div className="overflow-x-auto rounded-xl border border-rule">
        <table className="tabular w-full min-w-[34rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-xs text-ink-muted">
              <th className="py-3 pr-2 pl-4 font-medium">#</th>
              <th className="py-3 font-medium">{i18n.t("publicSite", "club")}</th>
              <th className="px-2 py-2 text-center font-medium">
                {i18n.t("publicSite", "played")}
              </th>
              <th className="px-2 py-2 text-center font-medium">{differenceLabel}</th>
              <th className="px-2 py-2 text-center font-medium">
                {i18n.t("publicSite", "points")}
              </th>
              <th className="hidden py-2 pl-2 font-medium sm:table-cell">
                {i18n.t("publicSite", "form")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.club.name}
                className="border-b border-rule last:border-0"
                // The club's own row, marked by the API rather than by matching
                // names — two clubs can share a name, and one of them is not us.
                style={
                  row.is_us
                    ? { background: "color-mix(in srgb, var(--brand) 8%, transparent)" }
                    : undefined
                }
              >
                <td className="py-3 pr-2 pl-4 text-ink-muted">{row.position}</td>
                <td className="py-2.5">
                  <span className="flex items-center gap-2">
                    <Crest club={row.club} size={20} />
                    <span className={row.is_us ? "font-semibold" : ""}>{row.club.name}</span>
                  </span>
                </td>
                <td className="px-2 py-2.5 text-center text-ink-muted">{row.played}</td>
                <td className="px-2 py-2.5 text-center text-ink-muted">
                  {row.goal_difference > 0 ? `+${row.goal_difference}` : row.goal_difference}
                </td>
                <td className="px-2 py-2.5 text-center font-semibold">{row.points}</td>
                <td className="hidden py-3 pr-4 pl-2 sm:table-cell">
                  <span className="flex gap-1">
                    {row.form.map((result, index) => (
                      <span
                        key={index}
                        title={result}
                        className="grid size-4 place-items-center rounded-[3px] text-[9px] font-bold text-white"
                        style={{
                          background:
                            result === "W"
                              ? "#1a8a4a"
                              : result === "D"
                                ? "#9a8f24"
                                : "#b3352c",
                        }}
                      >
                        {result}
                      </span>
                    ))}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
