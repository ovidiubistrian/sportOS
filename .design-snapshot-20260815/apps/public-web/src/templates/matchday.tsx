import type { Translator } from "@footbola/i18n";

import type { PublicMatch, PublicTableRow, Site } from "@/lib/site";

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

function Crest({ club, size = 28 }: { club: { name: string; crest_url: string | null }; size?: number }) {
  if (!club.crest_url) return null;
  return (
    <img
      src={club.crest_url}
      alt=""
      width={size}
      height={size}
      className="shrink-0 object-contain"
      style={{ width: size, height: size }}
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

  const ticketUrl = match.ticket_url ?? (match.is_home ? site.branding.tickets_url : null);

  return (
    /* A slim bar directly under the hero, not a screen of its own. The fixture
       is the question most visitors arrive with, so it sits high — but it is
       one line of fact, and giving it half a viewport made the club's own news
       the second thing on the page. */
    <section
      className="px-6 py-4"
      style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-6 gap-y-3 sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="font-display hidden text-[10px] font-bold tracking-[0.2em] uppercase opacity-70 sm:inline">
            {i18n.t("publicSite", "nextMatch")}
          </span>
          <Crest club={match.home} size={26} />
          <span className="text-sm font-semibold">{match.home.short_name}</span>
          <span className="text-xs opacity-60">—</span>
          <Crest club={match.away} size={26} />
          <span className="text-sm font-semibold">{match.away.short_name}</span>
        </div>

        <p className="tabular text-sm font-medium">
          {kickoffDay(match, site, locale)}
          {kickoffTime(match, site, locale) ? ` · ${kickoffTime(match, site, locale)}` : ""}
        </p>

        <p className="hidden text-xs opacity-70 lg:block">
          {[match.competition, match.round_label, match.venue_name]
            .filter(Boolean)
            .join(" · ")}
        </p>

        {ticketUrl && (
          <a
            href={ticketUrl}
            className="rounded-sm px-4 py-2 text-[11px] font-bold tracking-widest uppercase transition-opacity hover:opacity-90"
            style={{ background: "var(--brand-contrast)", color: "var(--brand)" }}
          >
            {site.branding.tickets_label || i18n.t("publicSite", "buyTickets")}
          </a>
        )}
      </div>

      {/* The club's own words, written in admin. Still here because it is
          nearly always about this match — just no longer the size of a hero. */}
      {site.branding.announcement && (
        <p className="mx-auto mt-3 max-w-3xl text-center text-xs opacity-85">
          {site.branding.announcement}
        </p>
      )}
    </section>
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
                {[match.competition, match.round_label].filter(Boolean).join(" · ")}
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
}: {
  rows: PublicTableRow[];
  i18n: Translator;
}) {
  if (rows.length === 0) return null;

  return (
    <section className="mx-auto max-w-5xl px-6 py-12">
      <h2 className="font-display mb-5 text-xs font-bold tracking-[0.2em] text-ink-muted uppercase">
        {i18n.t("publicSite", "standings")}
      </h2>

      {/* Its own scroll container: a table is the one block that legitimately
          exceeds a phone's width, and the page body must never scroll sideways
          because of it. */}
      <div className="overflow-x-auto">
        <table className="tabular w-full min-w-[34rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-xs text-ink-muted">
              <th className="py-2 pr-2 font-medium">#</th>
              <th className="py-2 font-medium">{i18n.t("publicSite", "club")}</th>
              <th className="px-2 py-2 text-center font-medium">
                {i18n.t("publicSite", "played")}
              </th>
              <th className="px-2 py-2 text-center font-medium">
                {i18n.t("publicSite", "goalDifference")}
              </th>
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
                <td className="py-2.5 pr-2 text-ink-muted">{row.position}</td>
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
                <td className="hidden py-2.5 pl-2 sm:table-cell">
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
