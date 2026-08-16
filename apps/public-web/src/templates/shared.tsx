import type { Translator } from "@footbola/i18n";
import Link from "next/link";
import type { ReactNode } from "react";

import type { Article, ArticleSummary, Block, Site, SquadPlayer, Team } from "@/lib/site";
import { formatDate } from "@/lib/site";

/**
 * Pieces every template composes from.
 *
 * A template changes layout, density and emphasis — not the content model. All
 * four render the same data through the same primitives, which is what stops
 * "four styles" becoming four codebases.
 */

/** Common to every view: the club, and the language the reader gets it in. */
export interface ViewProps {
  site: Site;
  i18n: Translator;
}

export interface TemplateProps extends ViewProps {
  teams: Team[];
}

export interface TeamViewProps extends ViewProps {
  team: Team;
  squad: SquadPlayer[];
}

export interface NewsListProps extends ViewProps {
  articles: ArticleSummary[];
}

export interface ArticleViewProps extends ViewProps {
  article: Article;
}

/** Catalogue keys, not words — the labels are resolved in the reader's language. */
export const NAV = [
  { href: "/", key: "home" },
  { href: "/news", key: "news" },
  { href: "/teams", key: "teams" },
  { href: "/shop", key: "shop" },
  { href: "/club", key: "club" },
] as const;

/**
 * Identity mark.
 *
 * A monogram, not an image: logo upload arrives with the media module. Built
 * from the club's short name and brand colour it reads as deliberate rather
 * than as a missing asset, and it works at any size in any template.
 */
export function Crest({
  site,
  size = 48,
  inverted = false,
}: {
  site: Site;
  size?: number;
  inverted?: boolean;
}) {
  // The club's own crest when it has uploaded one. Initials are the fallback,
  // not the design: a club with a badge should see its badge.
  if (site.branding.crest_url) {
    return (
      <img
        src={site.branding.crest_url}
        alt={site.branding.crest_alt ?? `${site.name} crest`}
        width={size}
        height={size}
        className="shrink-0 object-contain"
        style={{ width: size, height: size }}
      />
    );
  }

  const letters = site.short_name.slice(0, 3).toUpperCase();
  return (
    <span
      aria-hidden
      className="inline-grid shrink-0 place-items-center rounded-sm font-bold tracking-tight"
      style={{
        width: size,
        height: size,
        fontSize: Math.max(10, size * (letters.length > 2 ? 0.3 : 0.4)),
        background: inverted ? "var(--brand-contrast)" : "var(--brand)",
        color: inverted ? "var(--brand)" : "var(--brand-contrast)",
      }}
    >
      {letters}
    </span>
  );
}

/**
 * The band at the top of a page that is not the front page.
 *
 * There were five of these, written separately — teams, shop, account, a team,
 * an article — and they had drifted into five sizes of the same idea. One
 * component instead, so the pages read as one site and the rhythm is set in a
 * single place.
 *
 * Ink on the page rather than a slab of the club's colour. The eyebrow is
 * where the colour goes: enough to place the page as this club's, small enough
 * that the words stay the loudest thing.
 */
export function PageHeader({
  eyebrow,
  title,
  lead,
  children,
}: {
  eyebrow?: ReactNode;
  title: string;
  lead?: string;
  /** Facts, filters or actions belonging to the page, under the rule. */
  children?: ReactNode;
}) {
  return (
    <header className="border-b border-rule">
      <div className="mx-auto max-w-6xl px-6 pt-14 pb-10 sm:pt-20 sm:pb-12">
        {eyebrow && (
          <p
            className="text-[11px] font-bold tracking-[0.18em] uppercase"
            style={{ color: "var(--brand-text)" }}
          >
            {eyebrow}
          </p>
        )}
        <h1 className="font-display mt-3 text-[clamp(2rem,5vw,3.5rem)] leading-[1.02] font-extrabold tracking-[-0.03em] text-balance">
          {title}
        </h1>
        {lead && <p className="mt-4 max-w-xl text-base/relaxed text-ink-muted">{lead}</p>}
        {children}
      </div>
    </header>
  );
}

export function Established({ site }: { site: Site }) {
  if (!site.founded_year) return null;
  return (
    <span className="tabular text-xs tracking-widest uppercase opacity-70">
      Est. {site.founded_year}
    </span>
  );
}

export function SquadTable({
  squad,
  emptyLabel,
}: {
  squad: SquadPlayer[];
  emptyLabel?: string;
}) {
  if (squad.length === 0) {
    return <p className="py-8 text-sm text-ink-muted">{emptyLabel}</p>;
  }

  /* A grid of portraits, the way a club presents its squad — not a table.
     The shirt number is set very large behind the name because that is how a
     supporter finds a player they saw on the pitch and did not catch the name
     of. A player with no photograph gets the same card with the number alone,
     so a half-photographed squad still lines up. */
  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
      {squad.map((player) => (
        <li
          key={player.id}
          className="group relative flex flex-col overflow-hidden rounded-xl border border-rule transition-shadow duration-300 hover:shadow-[0_18px_40px_-24px_rgb(0_0_0/0.35)]"
        >
          <div
            className="relative aspect-[3/4] overflow-hidden"
            style={{ background: "color-mix(in srgb, var(--brand) 10%, transparent)" }}
          >
            {player.photo_url ? (
              <img
                src={player.photo_url}
                alt=""
                loading="lazy"
                className="h-full w-full object-cover object-top transition-transform duration-500 group-hover:scale-[1.04]"
              />
            ) : (
              <span
                aria-hidden
                className="tabular font-display absolute inset-0 grid place-items-center text-6xl font-extrabold opacity-15"
                style={{ color: "var(--brand)" }}
              >
                {player.shirt_number ?? "—"}
              </span>
            )}

            {player.photo_url && player.shirt_number != null && (
              <span
                aria-hidden
                className="tabular font-display absolute right-2 bottom-1 text-5xl leading-none font-extrabold text-white/85 mix-blend-overlay"
              >
                {player.shirt_number}
              </span>
            )}
          </div>

          <div className="flex items-baseline justify-between gap-2 px-3.5 py-3">
            <p className="truncate text-sm font-semibold">{player.name}</p>
            <p className="shrink-0 text-[11px] tracking-wider text-ink-muted uppercase">
              {player.position ?? ""}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function TeamLink({
  team,
  children,
  className,
}: {
  team: Team;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link href={`/teams/${team.id}`} className={className}>
      {children}
    </Link>
  );
}

export function groupTeams(teams: Team[]): { senior: Team[]; academy: Team[] } {
  return {
    senior: teams.filter((team) => !team.is_academy),
    academy: teams.filter((team) => team.is_academy),
  };
}

export function ClubFacts({ site, i18n }: ViewProps) {
  const facts: [string, string][] = [
    [i18n.t("publicSite", "founded"), site.founded_year ? String(site.founded_year) : "—"],
    [i18n.t("publicSite", "country"), site.country_code],
    [i18n.t("publicSite", "timeZone"), site.timezone],
  ];
  return (
    // Container query, not a viewport breakpoint: this block sits full-width in
    // one template and in a narrow sidebar in another, and it has to be right in
    // both without either template knowing about the other. The wrapper is the
    // container — an element cannot query its own width.
    <div className="@container">
      <dl className="grid gap-px overflow-hidden rounded-md border border-rule bg-rule @md:grid-cols-3">
        {facts.map(([label, value]) => (
          <div key={label} className="min-w-0 bg-page p-4">
            <dt className="text-xs tracking-wide text-ink-muted uppercase">{label}</dt>
            <dd className="tabular mt-1 truncate text-lg font-semibold" title={value}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}


/**
 * Block renderer.
 *
 * Every node is rendered as text — there is no `dangerouslySetInnerHTML`
 * anywhere in this app. Because the body is a validated list of typed blocks
 * rather than stored HTML, stored XSS is not something we sanitise against; it
 * is unrepresentable.
 */
export function ArticleBody({ blocks }: { blocks: Block[] }) {
  return (
    <div className="space-y-4">
      {blocks.map((block, index) => {
        switch (block.type) {
          case "heading":
            return block.level === 3 ? (
              <h3 key={index} className="font-display pt-2 text-base font-semibold">
                {block.text}
              </h3>
            ) : (
              <h2 key={index} className="font-display pt-3 text-xl font-semibold tracking-tight">
                {block.text}
              </h2>
            );
          case "quote":
            return (
              <blockquote
                key={index}
                className="border-l-2 pl-4 text-lg leading-relaxed text-balance italic"
                style={{ borderColor: "var(--brand)" }}
              >
                <p>{block.text}</p>
                {block.attribution && (
                  <footer className="mt-1.5 text-sm not-italic text-ink-muted">
                    — {block.attribution}
                  </footer>
                )}
              </blockquote>
            );
          case "list":
            return block.ordered ? (
              <ol key={index} className="list-decimal space-y-1 pl-5 leading-relaxed">
                {block.items.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ol>
            ) : (
              <ul key={index} className="list-disc space-y-1 pl-5 leading-relaxed">
                {block.items.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            );
          default:
            return (
              <p key={index} className="leading-relaxed">
                {block.text}
              </p>
            );
        }
      })}
    </div>
  );
}

export function ArticleDate({ article, site }: { article: ArticleSummary; site: Site }) {
  if (!article.published_at) return null;
  return (
    <time dateTime={article.published_at} className="text-xs text-ink-faint">
      {formatDate(article.published_at, site)}
    </time>
  );
}

/**
 * A section that has nothing in it yet.
 *
 * These were single sentences of muted text left-aligned in an otherwise empty
 * page, which reads as a page that failed rather than as a club that has not
 * filled this in yet — the shop was one line floating in half a screen of
 * white. Given a frame and centred, the same sentence reads as an answer.
 *
 * No illustration and no call to action: the person reading it is a supporter
 * who cannot do anything about it, and "check back soon" is not information.
 */
export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-rule px-6 py-16 text-center">
      <p className="mx-auto max-w-sm text-sm/relaxed text-ink-muted">{children}</p>
    </div>
  );
}

export function NewsEmpty() {
  return <EmptyState>There are no published articles yet.</EmptyState>;
}


/**
 * Staff sign-in.
 *
 * A club's own people go to the club's own address — that is the URL they know
 * and the one on the badge. Without a way in from here, "where do I log in?"
 * becomes a support question for every new staff member, so every template
 * carries this link in its footer. Quiet by design: it is for the handful of
 * people who run the club, not for supporters.
 */
/**
 * The supporter's way in, in the header of every template.
 *
 * Deliberately not the same link as the staff one in the footer: a supporter
 * and a volunteer running the club are different people arriving for different
 * reasons, and putting them behind one "sign in" is how a supporter ends up
 * staring at an admin console.
 *
 * One label for both states, and no cookie read here. It would be nicer to say
 * "Sign in" to a stranger and "My account" to a supporter — but this renders
 * inside the shell, so reading the session would turn every page on the club's
 * site into a per-request render and cost the whole site its cache. The label
 * stays honest either way, and `/cont` is where the two states diverge.
 */
export function AccountLink({
  inverted,
  label,
}: {
  inverted?: boolean;
  label: string;
}) {
  return (
    <Link
      href="/cont"
      className={
        inverted
          ? "rounded-full border px-3 py-1.5 text-xs font-bold tracking-widest uppercase opacity-80 transition-opacity hover:opacity-100"
          : // Solid, because on quiet chrome this is the one thing in the header
            // a supporter is meant to press, and an outline among six links is
            // not a call to action.
            "rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-opacity hover:opacity-90"
      }
      style={
        inverted
          ? { borderColor: "color-mix(in srgb, var(--brand-contrast) 35%, transparent)" }
          : { background: "var(--brand)", color: "var(--brand-contrast)" }
      }
    >
      {label}
    </Link>
  );
}

