"use client";

import { useEffect, useState } from "react";

import type { PublicMatch, Site } from "@/lib/site";

/**
 * The fixture strip: what a club puts directly under its hero.
 *
 * A countdown to the next kick-off, then the run of fixtures as cards. Cards
 * rather than rows because each one carries a crest, a competition, a ground
 * and sometimes a ticket link — five things that read as a block and become a
 * cramped table the moment they are a row.
 *
 * Client-side only for the countdown. The cards themselves are static, but the
 * clock has to tick, and splitting the two would mean two components that must
 * agree about which match is next.
 */

export interface CalendarLabels {
  calendar: string;
  nextMatch: string;
  days: string;
  hours: string;
  minutes: string;
  seconds: string;
  buyTickets: string;
  fullCalendar: string;
}

function useCountdown(target: string | null): {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
} | null {
  // Starts null and fills in on the client. Rendering a countdown on the server
  // would ship a number that is already wrong by the time it arrives, and
  // hydration would flag the mismatch.
  const [left, setLeft] = useState<number | null>(null);

  useEffect(() => {
    if (!target) return;
    const at = new Date(target).getTime();
    const tick = () => setLeft(Math.max(0, at - Date.now()));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [target]);

  if (left === null) return null;
  return {
    days: Math.floor(left / 86_400_000),
    hours: Math.floor((left % 86_400_000) / 3_600_000),
    minutes: Math.floor((left % 3_600_000) / 60_000),
    seconds: Math.floor((left % 60_000) / 1000),
  };
}

function Unit({ value, label }: { value: number; label: string }) {
  return (
    <div className="text-center">
      <p className="tabular font-display text-2xl leading-none font-extrabold sm:text-3xl">
        {String(value).padStart(2, "0")}
      </p>
      <p className="mt-1 text-[9px] tracking-[0.15em] text-ink-faint uppercase">{label}</p>
    </div>
  );
}

function Crest({ club, size = 40 }: { club: PublicMatch["home"]; size?: number }) {
  if (!club.crest_url) {
    return (
      <span
        className="grid shrink-0 place-items-center rounded-full text-[10px] font-bold"
        style={{
          width: size,
          height: size,
          background: "color-mix(in srgb, var(--brand-contrast) 15%, transparent)",
        }}
      >
        {club.short_name.slice(0, 3)}
      </span>
    );
  }
  return (
    <img
      src={club.crest_url}
      alt=""
      className="shrink-0 object-contain"
      style={{ width: size, height: size }}
    />
  );
}

export function MatchCalendar({
  site,
  matches,
  locale,
  labels,
}: {
  site: Site;
  matches: PublicMatch[];
  locale: string;
  labels: CalendarLabels;
}) {
  const next = matches.find((match) => match.kickoff_at && match.kickoff_is_confirmed);
  const countdown = useCountdown(next?.kickoff_at ?? null);

  if (matches.length === 0) return null;

  const dateOf = (match: PublicMatch) =>
    match.kickoff_at
      ? new Intl.DateTimeFormat(locale, {
          weekday: "long",
          day: "numeric",
          month: "long",
          ...(match.kickoff_is_confirmed
            ? { hour: "2-digit", minute: "2-digit" }
            : {}),
          timeZone: site.timezone,
        }).format(new Date(match.kickoff_at))
      : "—";

  return (
    <section className="mx-auto max-w-6xl px-6 py-12">
      <div className="mb-6 flex flex-wrap items-center gap-x-8 gap-y-4">
        <h2 className="font-display text-2xl font-extrabold tracking-tight uppercase sm:text-3xl">
          {labels.calendar}
        </h2>

        {countdown && (
          <div className="flex items-center gap-4">
            <p className="font-display text-[10px] font-bold tracking-[0.15em] text-ink-muted uppercase">
              {labels.nextMatch}
            </p>
            <div className="flex items-start gap-3">
              <Unit value={countdown.days} label={labels.days} />
              <Separator />
              <Unit value={countdown.hours} label={labels.hours} />
              <Separator />
              <Unit value={countdown.minutes} label={labels.minutes} />
              <Separator />
              <Unit value={countdown.seconds} label={labels.seconds} />
            </div>
          </div>
        )}
      </div>

      {/* Its own scroll container, so a club with six fixtures to show does not
          make the page scroll sideways on a phone. */}
      <div className="-mx-6 overflow-x-auto px-6 pb-2">
        <ul className="flex gap-4">
          {matches.map((match) => (
            <li
              key={match.id}
              className="flex w-[17rem] shrink-0 flex-col overflow-hidden rounded-lg border border-rule"
            >
              <div
                className="flex items-center justify-center gap-4 px-5 py-6"
                style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
              >
                <div className="flex w-20 flex-col items-center gap-2 text-center">
                  <Crest club={match.home} />
                  <span className="text-[11px] leading-tight font-semibold">
                    {match.home.name}
                  </span>
                </div>
                <span className="text-xs opacity-60">—</span>
                <div className="flex w-20 flex-col items-center gap-2 text-center">
                  <Crest club={match.away} />
                  <span className="text-[11px] leading-tight font-semibold">
                    {match.away.name}
                  </span>
                </div>
              </div>

              <div className="flex flex-1 flex-col gap-1.5 p-4 text-xs">
                <p className="font-semibold text-ink">{dateOf(match)}</p>
                <p className="text-ink-muted">
                  {[match.competition, match.round_label].filter(Boolean).join(", ")}
                </p>
                {match.venue_name && <p className="text-ink-muted">{match.venue_name}</p>}

                {/* The club's own box office only sells its own home games.
                    An away fixture shows a link only if the club put one on
                    that specific match — usually the host's allocation. */}
                {(match.ticket_url ?? (match.is_home ? site.branding.tickets_url : null)) && (
                  <a
                    href={match.ticket_url ?? site.branding.tickets_url ?? "#"}
                    className="mt-auto block rounded-sm px-4 py-2.5 pt-2.5 text-center text-[11px] font-bold tracking-widest uppercase transition-opacity hover:opacity-90"
                    style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
                  >
                    {labels.buyTickets}
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Separator() {
  return <span className="font-display pt-0.5 text-xl leading-none text-ink-faint">:</span>;
}
