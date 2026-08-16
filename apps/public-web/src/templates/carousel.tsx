"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { ArticleSummary, Site } from "@/lib/site";

/**
 * The news hero.
 *
 * The first thing a supporter sees, so it shows the club's own words rather
 * than a stock band of colour: the latest articles, largest first, advancing on
 * their own.
 *
 * A client component because it advances and can be steered — the only one on
 * the club site. Everything under it stays server-rendered, which is what keeps
 * the page fast for the visitor who arrives, reads the top story and leaves.
 */

const INTERVAL = 7000;

export function NewsCarousel({
  site,
  articles,
  labels,
}: {
  site: Site;
  articles: ArticleSummary[];
  /** Resolved server-side: this component cannot reach the translator. */
  labels: { news: string; readMore: string; previous: string; next: string };
}) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  const count = articles.length;

  useEffect(() => {
    // One slide is a picture, not a carousel; and a reader who has taken hold
    // of it should not have it moved out from under them.
    if (count < 2 || paused) return;
    const timer = window.setInterval(
      () => setIndex((current) => (current + 1) % count),
      INTERVAL,
    );
    return () => window.clearInterval(timer);
  }, [count, paused]);

  useEffect(() => {
    // Respect a reader who has asked for stillness.
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (media.matches) setPaused(true);
  }, []);

  if (count === 0) return null;

  const go = (next: number) => {
    setIndex(((next % count) + count) % count);
    setPaused(true);
  };

  return (
    <section
      aria-roledescription="carousel"
      aria-label={labels.news}
      // Neutral dark, not the club's colour: every slide is a photograph with a
      // dark scrim over it, so on a club with a strong colour the ground only
      // showed while the image loaded — a flash of saturation, then nothing.
      // It is also what a club with no cover images falls back to, and text
      // over near-black is legible in a way text over an arbitrary hue is not.
      className="relative isolate overflow-hidden bg-surface-deep text-surface-deep-ink"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="relative h-[380px] sm:h-[460px] lg:h-[540px]">
        {articles.map((article, position) => {
          const active = position === index;
          // Every slide is mounted and cross-faded, so the picture is already
          // decoded when its turn comes and the hero never flashes empty.
          const background = article.cover_url ?? site.branding.hero_url;
          return (
            <article
              key={article.id}
              aria-hidden={!active}
              className="absolute inset-0 transition-opacity duration-700 ease-out"
              style={{ opacity: active ? 1 : 0, pointerEvents: active ? "auto" : "none" }}
            >
              {background && (
                <img
                  src={background}
                  alt=""
                  className="absolute inset-0 h-full w-full object-cover"
                  // The first slide is the page's largest paint; the rest can
                  // wait until the reader is actually on them.
                  loading={position === 0 ? "eager" : "lazy"}
                  fetchPriority={position === 0 ? "high" : "low"}
                />
              )}
              <span
                aria-hidden
                className="absolute inset-0"
                style={{
                  background:
                    "linear-gradient(to top, rgb(0 0 0 / 0.82) 0%, rgb(0 0 0 / 0.45) 45%, rgb(0 0 0 / 0.12) 100%)",
                }}
              />

              <div className="relative mx-auto flex h-full max-w-6xl flex-col justify-end px-6 pb-12 text-white sm:pb-16">
                <p className="font-display text-[11px] font-bold tracking-[0.2em] uppercase opacity-80">
                  {labels.news}
                </p>
                <h2 className="font-display mt-3 max-w-3xl text-3xl leading-[1.05] font-extrabold tracking-tight text-balance sm:text-5xl lg:text-6xl">
                  {article.title}
                </h2>
                {article.excerpt && (
                  <p className="mt-4 hidden max-w-xl text-sm/relaxed opacity-90 sm:block">
                    {article.excerpt}
                  </p>
                )}
                <Link
                  href={`/news/${article.slug}`}
                  tabIndex={active ? 0 : -1}
                  className="mt-6 inline-flex w-fit items-center rounded-sm px-5 py-2.5 text-xs font-bold tracking-widest uppercase transition-opacity hover:opacity-90"
                  style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
                >
                  {labels.readMore}
                </Link>
              </div>
            </article>
          );
        })}
      </div>

      {count > 1 && (
        <div className="absolute inset-x-0 bottom-5 mx-auto flex max-w-6xl items-center gap-3 px-6">
          <div className="flex gap-2">
            {articles.map((article, position) => (
              <button
                key={article.id}
                type="button"
                aria-label={article.title}
                aria-current={position === index}
                onClick={() => go(position)}
                className="h-1 rounded-full bg-white transition-all"
                style={{
                  width: position === index ? 28 : 10,
                  opacity: position === index ? 1 : 0.45,
                }}
              />
            ))}
          </div>
          <div className="ml-auto flex gap-1.5">
            <CarouselArrow label={labels.previous} onClick={() => go(index - 1)} back />
            <CarouselArrow label={labels.next} onClick={() => go(index + 1)} />
          </div>
        </div>
      )}
    </section>
  );
}

function CarouselArrow({
  label,
  onClick,
  back,
}: {
  label: string;
  onClick: () => void;
  back?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="grid size-8 place-items-center rounded-full border border-white/35 text-white transition-colors hover:bg-white/15"
    >
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={2}>
        <path
          d={back ? "M15 18l-6-6 6-6" : "M9 18l6-6-6-6"}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
