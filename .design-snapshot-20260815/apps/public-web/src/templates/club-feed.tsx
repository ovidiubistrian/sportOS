"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import type { ArticleSummary, Site } from "@/lib/site";

/**
 * The club feed: everything else the club has to say.
 *
 * News, signings, departures, academy notes — one carousel rather than four
 * sections, because a club does not produce them at four steady rates. In a
 * quiet week it is three match reports; in January it is five transfers. A row
 * that reorders itself by date handles both, where four fixed sections would be
 * mostly empty most of the season.
 *
 * The kind of each item is a badge rather than a heading, so a supporter can
 * tell a signing from a match report before reading either.
 */

export interface FeedLabels {
  title: string;
  subtitle: string;
  readMore: string;
  previous: string;
  next: string;
  /** Keyed by `article_type`, falling back to the raw value. */
  types: Record<string, string>;
}

/** A tint per kind, derived from the club's colour rather than picked. */
const TINT: Record<string, string> = {
  SIGNING: "color-mix(in srgb, var(--brand) 88%, white)",
  DEPARTURE: "color-mix(in srgb, var(--brand) 55%, black)",
  MATCH_REPORT: "var(--brand)",
  MATCH_PREVIEW: "var(--brand)",
  ACADEMY: "color-mix(in srgb, var(--brand) 70%, white)",
  INTERVIEW: "color-mix(in srgb, var(--brand) 70%, black)",
};

export function ClubFeed({
  site,
  articles,
  labels,
}: {
  site: Site;
  articles: ArticleSummary[];
  labels: FeedLabels;
}) {
  const rail = useRef<HTMLUListElement>(null);
  const [atStart, setAtStart] = useState(true);
  const [atEnd, setAtEnd] = useState(false);

  if (articles.length === 0) return null;

  const onScroll = () => {
    const node = rail.current;
    if (!node) return;
    setAtStart(node.scrollLeft < 8);
    setAtEnd(node.scrollLeft + node.clientWidth >= node.scrollWidth - 8);
  };

  const nudge = (direction: 1 | -1) => {
    const node = rail.current;
    if (!node) return;
    // One card plus its gap, so a click always lands on a card edge rather
    // than halfway through one.
    node.scrollBy({ left: direction * (node.clientWidth * 0.8), behavior: "smooth" });
  };

  return (
    <section className="py-14">
      <div className="mx-auto mb-7 flex max-w-6xl items-end justify-between gap-6 px-6">
        <div>
          <h2 className="font-display text-2xl font-extrabold tracking-tight uppercase sm:text-3xl">
            {labels.title}
          </h2>
          <p className="mt-1 text-sm text-ink-muted">{labels.subtitle}</p>
        </div>

        <div className="hidden shrink-0 gap-2 sm:flex">
          <Arrow label={labels.previous} onClick={() => nudge(-1)} disabled={atStart} back />
          <Arrow label={labels.next} onClick={() => nudge(1)} disabled={atEnd} />
        </div>
      </div>

      {/* Same container as the heading, so the first card lines up under it;
          the negative margin lets the row bleed to the edge as it scrolls. */}
      <div className="mx-auto max-w-6xl px-6">
        <ul
          ref={rail}
          onScroll={onScroll}
          className="-mx-6 flex snap-x snap-mandatory gap-5 overflow-x-auto px-6 pb-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {articles.map((article) => (
            <li
              key={article.id}
              className="w-[16.5rem] shrink-0 snap-start sm:w-[18rem]"
            >
            <Link
              href={`/news/${article.slug}`}
              className="group flex h-full flex-col overflow-hidden rounded-2xl border border-rule bg-page transition-shadow duration-300 hover:shadow-[0_18px_40px_-24px_rgb(0_0_0/0.45)]"
            >
              <div className="relative aspect-[3/4] overflow-hidden">
                {(article.cover_url ?? site.branding.hero_url) && (
                  <img
                    src={article.cover_url ?? site.branding.hero_url ?? ""}
                    alt=""
                    loading="lazy"
                    className="h-full w-full object-cover transition-transform duration-[600ms] ease-out group-hover:scale-[1.05]"
                  />
                )}
                <span
                  className="absolute top-3 left-3 rounded-full px-2.5 py-1 text-[10px] font-bold tracking-[0.12em] text-white uppercase"
                  style={{ background: TINT[article.article_type] ?? "var(--brand)" }}
                >
                  {labels.types[article.article_type] ?? article.article_type}
                </span>
              </div>

              <div className="flex flex-1 flex-col p-5">
                <h3 className="font-display text-lg leading-snug font-bold text-balance">
                  {article.title}
                </h3>
                {article.excerpt && (
                  <p className="mt-2 line-clamp-3 text-sm/relaxed text-ink-muted">
                    {article.excerpt}
                  </p>
                )}
                <span className="mt-5 inline-flex items-center gap-1.5 text-sm font-semibold text-brand-text">
                  {labels.readMore}
                  <svg
                    viewBox="0 0 24 24"
                    className="size-4 transition-transform duration-300 group-hover:translate-x-1"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2.5}
                  >
                    <path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
              </div>
            </Link>
            </li>
          ))}
        </ul>
      </div>

    </section>
  );
}

function Arrow({
  label,
  onClick,
  disabled,
  back,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  back?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className="grid size-10 place-items-center rounded-full border border-rule transition-colors hover:border-[var(--brand)] hover:text-brand-text disabled:opacity-30 disabled:hover:border-rule disabled:hover:text-inherit"
    >
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={2.5}>
        <path
          d={back ? "M15 18l-6-6 6-6" : "M9 18l6-6-6-6"}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
