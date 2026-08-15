import { SiteFooter } from "./footer";
import type { Translator } from "@footbola/i18n";
import Link from "next/link";

import { formatDate } from "@/lib/site";
import type { ReactNode } from "react";

import {
  ArticleBody,
  ArticleDate,
  Crest,
  AccountLink,
  NAV,
  NewsEmpty,
  SquadTable,
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
          <div className="flex items-center gap-5">
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
            <AccountLink
              inverted
              label={i18n.t("publicSite", "accountNav")}
            />
          </div>
        </div>
      </header>

      {children}

      <footer
        className="mt-16 py-12"
        style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
      >
        <SiteFooter
          site={site}
          inverted
          labels={{
            contact: i18n.t("publicSite", "footerContact"),
            address: i18n.t("publicSite", "footerAddress"),
            follow: i18n.t("publicSite", "footerFollow"),
            sponsors: i18n.t("publicSite", "footerSponsors"),
            staffSignIn: i18n.t("publicSite", "staffSignIn"),
            account: i18n.t("publicSite", "accountNav"),
          }}
        />
      </footer>
    </div>
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
        <SquadTable squad={squad} emptyLabel={i18n.t("publicSite", "squadUnpublished")} />
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
