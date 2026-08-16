"use client";

import { useEffect, useState } from "react";

import { roundLabel } from "@/lib/round";
import type { PublicMatch, Site } from "@/lib/site";
import { SectionHeading } from "./section";

/**
 * The fixture list, grouped by month.
 *
 * Rows rather than cards. A club's calendar is read down a column — when do we
 * play next, and the one after that — and a row puts the date, the competition,
 * the fixture and the ticket link on one line the eye can scan. Cards made each
 * fixture a destination, which is the wrong shape for a list somebody checks
 * twice a week.
 *
 * Client-side only for the countdown; everything below it is static.
 */

export interface CalendarLabels {
  calendar: string;
  nextMatch: string;
  days: string;
  hours: string;
  minutes: string;
  seconds: string;
  buyTickets: string;
  tbc: string;
  matchday: string;
}

function useCountdown(target: string | null) {
  // Starts null and fills in on the client: a countdown rendered on the server
  // is already wrong by the time it arrives, and hydration would flag it.
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

function Crest({ club }: { club: PublicMatch["home"] }) {
  if (!club.crest_url) {
    return (
      <span
        className="grid size-10 shrink-0 place-items-center rounded-full text-[10px] font-bold text-ink-muted sm:size-11"
        style={{ background: "color-mix(in srgb, var(--brand) 12%, transparent)" }}
      >
        {club.short_name.slice(0, 3)}
      </span>
    );
  }
  return (
    <img src={club.crest_url} alt="" className="size-10 shrink-0 object-contain sm:size-11" />
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
  // The next match that has not started. A fixture already under way counts
  // down to zero and sits there, which reads as a broken clock rather than as
  // a game in progress — the scoreboard above says LIVE for that.
  const next = matches.find(
    (match) =>
      match.kickoff_at &&
      match.kickoff_is_confirmed &&
      new Date(match.kickoff_at).getTime() > Date.now(),
  );
  const countdown = useCountdown(next?.kickoff_at ?? null);

  if (matches.length === 0) return null;

  const fmt = (match: PublicMatch, options: Intl.DateTimeFormatOptions) =>
    match.kickoff_at
      ? new Intl.DateTimeFormat(locale, { ...options, timeZone: site.timezone }).format(
          new Date(match.kickoff_at),
        )
      : "";

  // Grouped in order rather than sorted into a map, so a fixture list that
  // straddles a new year stays in the order the club plays it.
  const groups: { month: string; fixtures: PublicMatch[] }[] = [];
  for (const match of matches) {
    const month = fmt(match, { month: "long", year: "numeric" }) || "—";
    const last = groups.at(-1);
    if (last && last.month === month) last.fixtures.push(match);
    else groups.push({ month, fixtures: [match] });
  }

  return (
    <section className="mx-auto max-w-6xl px-6 py-14">
      <SectionHeading
        eyebrow={labels.nextMatch}
        title={labels.calendar}
        action={
          countdown && (
            <div className="flex items-start gap-2 sm:gap-3">
              <Unit value={countdown.days} label={labels.days} />
              <Colon />
              <Unit value={countdown.hours} label={labels.hours} />
              <Colon />
              <Unit value={countdown.minutes} label={labels.minutes} />
              <Colon />
              <Unit value={countdown.seconds} label={labels.seconds} />
            </div>
          )
        }
      />

      {groups.map((group) => (
        <div key={group.month} className="mb-10 last:mb-0">
          <h3 className="font-display mb-2 text-sm font-bold tracking-[0.12em] text-ink-muted uppercase">
            {group.month}
          </h3>
          <span
            aria-hidden
            className="mb-1 block h-px w-full"
            style={{
              background:
                "linear-gradient(to right, color-mix(in srgb, var(--brand) 55%, transparent), transparent)",
            }}
          />

          <ul>
            {group.fixtures.map((match) => {
              const ticketUrl =
                match.ticket_url ?? (match.is_home ? site.branding.tickets_url : null);

              return (
                <li
                  key={match.id}
                  className="flex flex-col gap-3 border-b border-rule py-4 last:border-0 lg:grid lg:grid-cols-[7.5rem_9rem_1fr_11.5rem] lg:items-center lg:gap-x-6 lg:py-5"
                >
                  {/* The fixture leads on a phone and sits third on a desktop.
                      One markup, two layouts: `order` moves it, and `contents`
                      lets the date and competition — one line on a phone —
                      become their own grid columns on a wide screen. */}
                  <div className="order-1 grid grid-cols-[1fr_auto_1fr] items-center gap-2 sm:gap-3 lg:order-3">
                    {/* `min-w-0` on both sides: a grid track is `auto`-sized by
                        default and will not go below its content, so a pair of
                        long club names widened the whole page on a phone rather
                        than wrapping or clipping. */}
                    <span className="flex min-w-0 items-center justify-end gap-2 text-right sm:gap-2.5">
                      <span className="truncate text-sm font-bold sm:text-base">
                        {match.home.name}
                      </span>
                      <Crest club={match.home} />
                    </span>
                    <span className="shrink-0 text-[11px] font-semibold text-ink-faint">
                      vs.
                    </span>
                    <span className="flex min-w-0 items-center gap-2 sm:gap-2.5">
                      <Crest club={match.away} />
                      <span className="truncate text-sm font-bold sm:text-base">
                        {match.away.name}
                      </span>
                    </span>
                  </div>

                  <div className="order-2 flex flex-wrap items-baseline justify-center gap-x-3 gap-y-1 text-xs lg:contents">
                    <p className="lg:order-1">
                      <span className="text-sm font-bold tracking-wide uppercase">
                        {fmt(match, { weekday: "short", day: "numeric", month: "short" })}
                      </span>
                      <span
                        className="tabular ml-2 text-sm font-semibold lg:ml-0 lg:mt-0.5 lg:block"
                        style={{ color: "var(--brand)" }}
                      >
                        {match.kickoff_is_confirmed
                          ? fmt(match, { hour: "2-digit", minute: "2-digit" })
                          : labels.tbc}
                      </span>
                    </p>

                    <p className="text-xs lg:order-2">
                      <span className="font-display font-bold tracking-wide uppercase">
                        {match.competition}
                      </span>
                      <span className="ml-2 text-ink-muted lg:mt-0.5 lg:ml-0 lg:block">
                        {roundLabel(match, labels.matchday)}
                      </span>
                      {match.venue_name && (
                        <span className="ml-2 hidden text-ink-faint lg:mt-0.5 lg:ml-0 lg:block">
                          {match.venue_name}
                        </span>
                      )}
                    </p>
                  </div>

                  {ticketUrl ? (
                    <a
                      href={ticketUrl}
                      className="order-3 inline-flex w-full items-center justify-center gap-2 rounded-full px-5 py-3 text-xs font-bold tracking-wider uppercase transition-opacity hover:opacity-90 lg:order-4 lg:w-auto lg:py-2.5"
                      style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
                    >
                      <TicketIcon />
                      {labels.buyTickets}
                    </a>
                  ) : (
                    <span aria-hidden className="hidden lg:order-4 lg:block" />
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </section>
  );
}

function Colon() {
  return <span className="font-display pt-0.5 text-xl leading-none text-ink-faint">:</span>;
}

function TicketIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2}>
      <path
        d="M3 9a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2 2 2 0 0 0 0 4 2 2 0 0 1-2 2H5a2 2 0 0 1-2-2 2 2 0 0 0 0-4Z"
        strokeLinejoin="round"
      />
      <path d="M13 7v10" strokeDasharray="2 2" strokeLinecap="round" />
    </svg>
  );
}
