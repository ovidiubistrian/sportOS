import type { Translator } from "@footbola/i18n";
import Link from "next/link";

import { formatDate } from "@/lib/site";
import type { ReactNode } from "react";

import {
  ArticleBody,
  ArticleDate,
  ClubFacts,
  Crest,
  NAV,
  NewsEmpty,
  SquadTable,
  StaffLink,
  TeamLink,
  groupTeams,
  type ArticleViewProps,
  type NewsListProps,
  type TeamViewProps,
  type TemplateProps,
} from "./shared";

/**
 * BOLD — the modern professional club.
 *
 * A full-bleed brand-colour hero, the club name set very large and tight, and
 * team cards that fill with the brand colour on hover. The one template that
 * uses the brand colour as a large surface — which is safe precisely because
 * the API supplies `--brand-contrast`, a black or white chosen for readability
 * against whatever colour the club picked. A yellow club and a navy club both
 * get legible hero text.
 */

export function Shell({
  site,
  children,
  i18n,
}: {
  site: TemplateProps["site"];
  children: ReactNode;
  i18n: Translator;
}) {
  return (
    <div className="min-h-screen bg-page">
      <header
        className="sticky top-0 z-20 border-b"
        style={{
          background: "var(--brand)",
          color: "var(--brand-contrast)",
          borderColor: "color-mix(in srgb, var(--brand-contrast) 20%, transparent)",
        }}
      >
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <Crest site={site} size={30} inverted />
            <span className="font-display text-sm font-extrabold tracking-tight uppercase">
              {site.short_name}
            </span>
          </Link>
          <nav aria-label="Main">
            <ul className="flex gap-6">
              {NAV.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className="text-xs font-bold tracking-widest uppercase opacity-80 hover:opacity-100"
                  >
                    {i18n.t("publicSite", item.key)}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>

      {children}

      <footer
        className="mt-16 py-12"
        style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
      >
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6">
          <Crest site={site} size={40} inverted />
          <p className="font-display text-2xl font-extrabold tracking-tight">{site.name}</p>
          <p className="text-xs opacity-70">
            © {new Date().getFullYear()} {site.name}
            {site.founded_year
              ? ` · ${i18n.t("publicSite", "established")} ${site.founded_year}`
              : ""}
          </p>
          <StaffLink inverted label={i18n.t("publicSite", "staffSignIn")} />
        </div>
      </footer>
    </div>
  );
}

export function Squads({ site, i18n, teams }: TemplateProps) {
  const { senior, academy } = groupTeams(teams);
  return (
    <>
      {/* The club's photograph when it has one, its colour when it does not.
          A scrim rather than a flat overlay: the name has to stay readable over
          a bright sky as well as over a dark stand, and the club chose the
          picture — dimming it into mud is not an improvement. */}
      <section
        className="relative overflow-hidden px-6 py-20 sm:py-28"
        style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
      >
        {site.branding.hero_url && (
          <>
            <img
              src={site.branding.hero_url}
              alt={site.branding.hero_alt ?? ""}
              className="absolute inset-0 h-full w-full object-cover"
            />
            <span
              aria-hidden
              className="absolute inset-0"
              style={{
                background:
                  "linear-gradient(to top, rgb(0 0 0 / 0.72) 0%, rgb(0 0 0 / 0.35) 45%, rgb(0 0 0 / 0.15) 100%)",
              }}
            />
          </>
        )}
        <div className="relative mx-auto max-w-6xl">
          {site.branding.crest_url && (
            <Crest site={site} size={88} />
          )}
          <h1 className="font-display mt-6 text-5xl leading-[0.95] font-extrabold tracking-[-0.03em] uppercase sm:text-7xl lg:text-8xl">
            {site.name}
          </h1>
          {site.branding.tagline && (
            <p className="mt-6 max-w-xl text-lg opacity-85">{site.branding.tagline}</p>
          )}
          <Link
            href="/teams"
            className="mt-10 inline-block rounded-sm px-6 py-3 text-sm font-bold tracking-widest uppercase transition-opacity hover:opacity-90"
            style={{ background: "var(--brand-contrast)", color: "var(--brand)" }}
          >
            {i18n.t("publicSite", "ourTeams")}
          </Link>
        </div>
      </section>

      <main className="mx-auto max-w-6xl space-y-14 px-6 py-14">
        {senior.length > 0 && (
          <section>
            <h2 className="mb-5 font-display text-xs font-bold tracking-[0.2em] text-ink-muted uppercase">
              {i18n.t("publicSite", "senior")}
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {senior.map((team) => (
                <TeamLink
                  key={team.id}
                  team={team}
                  className="group relative overflow-hidden rounded-lg border border-rule p-6 transition-colors hover:border-transparent"
                >
                  <span
                    className="absolute inset-0 opacity-0 transition-opacity group-hover:opacity-100"
                    style={{ background: "var(--brand)" }}
                  />
                  <span className="relative block font-display text-2xl font-extrabold tracking-tight group-hover:text-[var(--brand-contrast)]">
                    {team.name}
                  </span>
                  <span className="relative mt-1 block text-xs tracking-widest text-ink-muted uppercase group-hover:text-[var(--brand-contrast)] group-hover:opacity-80">
                    {team.code}
                  </span>
                </TeamLink>
              ))}
            </div>
          </section>
        )}

        {academy.length > 0 && (
          <section>
            <h2 className="mb-5 font-display text-xs font-bold tracking-[0.2em] text-ink-muted uppercase">
              {i18n.t("publicSite", "academy")} · {academy.length}
            </h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
              {academy.map((team) => (
                <TeamLink
                  key={team.id}
                  team={team}
                  className="rounded-md border border-rule px-4 py-5 text-center transition-colors hover:border-[var(--brand)]"
                >
                  <span className="font-display block text-xl font-extrabold tracking-tight text-brand-text">
                    {team.age_group ?? team.code}
                  </span>
                </TeamLink>
              ))}
            </div>
          </section>
        )}

        <section>
          <h2 className="mb-5 font-display text-xs font-bold tracking-[0.2em] text-ink-muted uppercase">
            {i18n.t("publicSite", "theClub")}
          </h2>
          <ClubFacts site={site} i18n={i18n} />
        </section>
      </main>
    </>
  );
}

export function TeamView({ i18n, team, squad }: TeamViewProps) {
  return (
    <>
      <section
        className="px-6 py-14"
        style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
      >
        <div className="mx-auto max-w-6xl">
          <p className="text-xs font-bold tracking-[0.2em] uppercase opacity-75">
            {i18n.t("publicSite", team.is_academy ? "academy" : "senior")}
          </p>
          <h1 className="font-display mt-2 text-4xl font-extrabold tracking-[-0.02em] uppercase sm:text-6xl">
            {team.name}
          </h1>
        </div>
      </section>
      <main className="mx-auto max-w-6xl px-6 py-10">
        <SquadTable squad={squad} />
        <Link href="/teams" className="mt-8 inline-block text-sm font-semibold text-brand-text">
          ← {i18n.t("publicSite", "ourTeams")}
        </Link>
      </main>
    </>
  );
}


export function NewsList({ site, i18n, articles }: NewsListProps) {
  return (
    <main className="mx-auto max-w-6xl px-6 py-14">
      <h1 className="font-display mb-8 text-4xl font-extrabold tracking-tighter uppercase">
        {i18n.t("publicSite", "news")}
      </h1>
      {articles.length === 0 ? (
        <NewsEmpty />
      ) : (
        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {articles.map((article) => (
            <Link
              key={article.id}
              href={`/news/${article.slug}`}
              className="group flex flex-col rounded-lg border border-rule p-5 transition-colors hover:border-[var(--brand)]"
            >
              {article.is_pinned && (
                <span
                  className="mb-2 self-start rounded-sm px-1.5 py-0.5 text-[10px] font-bold tracking-widest uppercase"
                  style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
                >
                  Featured
                </span>
              )}
              <h2 className="font-display text-xl leading-tight font-extrabold tracking-tight text-balance group-hover:text-brand-text">
                {article.title}
              </h2>
              {article.excerpt && (
                <p className="mt-2 line-clamp-3 flex-1 text-sm text-ink-muted">
                  {article.excerpt}
                </p>
              )}
              <div className="mt-4">
                <ArticleDate article={article} site={site} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}

export function ArticleView({ site, i18n, article }: ArticleViewProps) {
  return (
    <>
      <header
        className="px-6 py-14"
        style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
      >
        <div className="mx-auto max-w-3xl">
          <p className="text-xs font-bold tracking-[0.2em] uppercase opacity-75">{i18n.t("publicSite", "news")}</p>
          <h1 className="font-display mt-3 text-3xl leading-[1.05] font-extrabold tracking-tight text-balance sm:text-5xl">
            {article.title}
          </h1>
          {article.published_at && (
            <p className="mt-4 text-sm opacity-80">
              {formatDate(article.published_at, site)}
            </p>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-6 py-10 text-[15px]">
        <ArticleBody blocks={article.body} />
        <Link href="/news" className="mt-10 inline-block text-sm font-semibold text-brand-text">
          ← {i18n.t("publicSite", "allNews")}
        </Link>
      </main>
    </>
  );
}
