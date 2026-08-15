import { SiteFooter } from "./footer";
import type { Translator } from "@footbola/i18n";
import Link from "next/link";
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
 * EDITORIAL — magazine layout.
 *
 * Asymmetric grid, generous whitespace, hairline rules, teams as a numbered
 * index. Built for the club that publishes: it gives long-form content room to
 * breathe and treats the squad as an index rather than a table. Brand colour
 * appears only in the rule above the masthead and in the index numerals.
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
      <header className="border-b border-ink/10">
        <div className="mx-auto max-w-6xl px-6">
          <div className="flex items-center justify-between py-5">
            <Link href="/" className="flex items-baseline gap-3">
              <Crest site={site} size={34} />
              <span className="font-display text-lg font-semibold tracking-tight">
                {site.name}
              </span>
            </Link>
            <div className="flex items-center gap-6">
              <nav aria-label="Main">
                <ul className="flex gap-7">
                  {NAV.map((item) => (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className="text-[13px] text-ink-muted hover:text-brand-text"
                      >
                        {i18n.t("publicSite", item.key)}
                      </Link>
                    </li>
                  ))}
                </ul>
              </nav>
              <AccountLink
                label={i18n.t("publicSite", "accountNav")}
              />
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-12">{children}</main>

      <footer className="mt-16 border-t border-ink/10 py-10">
        <SiteFooter
          site={site}
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

function Rule({ label }: { label: string }) {
  return (
    <div className="mb-6 flex items-center gap-4">
      <h2 className="font-display text-sm font-semibold tracking-[0.15em] uppercase">
        {label}
      </h2>
      <span className="h-px flex-1" style={{ background: "var(--brand)" }} />
    </div>
  );
}

export function TeamView({ i18n, team, squad }: TeamViewProps) {
  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_2fr]">
      <div className="lg:sticky lg:top-10 lg:self-start">
        <p className="text-xs tracking-[0.2em] text-brand-text uppercase">
          {i18n.t("publicSite", team.is_academy ? "academy" : "senior")}
        </p>
        <h1 className="font-display mt-2 text-3xl font-semibold tracking-tight">
          {team.name}
        </h1>
        <p className="tabular mt-3 text-sm text-ink-muted">{i18n.plural("publicSite", "playerCount", squad.length)}</p>
        <Link
          href="/teams"
          className="mt-6 inline-block text-sm text-ink-muted hover:text-brand-text"
        >
          ← {i18n.t("publicSite", "ourTeams")}
        </Link>
      </div>
      <div>
        <SquadTable squad={squad} emptyLabel={i18n.t("publicSite", "squadUnpublished")} />
      </div>
    </div>
  );
}


export function NewsList({ site, i18n, articles }: NewsListProps) {
  const [lead, ...rest] = articles;
  return (
    <div className="space-y-12">
      <Rule label={i18n.t("publicSite", "news")} />
      {articles.length === 0 ? (
        <NewsEmpty />
      ) : (
        <>
          {lead && (
            <Link href={`/news/${lead.slug}`} className="group block max-w-3xl">
              <ArticleDate article={lead} site={site} />
              <h2 className="font-display mt-2 text-3xl leading-tight font-semibold tracking-tight text-balance group-hover:text-brand-text sm:text-4xl">
                {lead.title}
              </h2>
              {lead.excerpt && (
                <p className="mt-3 max-w-prose leading-relaxed text-ink-muted">
                  {lead.excerpt}
                </p>
              )}
            </Link>
          )}
          {rest.length > 0 && (
            <ol className="divide-y divide-ink/10 border-y border-ink/10">
              {rest.map((article, index) => (
                <li key={article.id}>
                  <Link
                    href={`/news/${article.slug}`}
                    className="group grid gap-2 py-5 sm:grid-cols-[3rem_1fr_auto]"
                  >
                    <span className="tabular text-sm text-ink-faint">
                      {String(index + 2).padStart(2, "0")}
                    </span>
                    <span>
                      <span className="font-display block text-lg font-medium group-hover:text-brand-text">
                        {article.title}
                      </span>
                      {article.excerpt && (
                        <span className="mt-1 block text-sm text-ink-muted">
                          {article.excerpt}
                        </span>
                      )}
                    </span>
                    <ArticleDate article={article} site={site} />
                  </Link>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  );
}

export function ArticleView({ site, i18n, article }: ArticleViewProps) {
  return (
    <article className="grid gap-10 lg:grid-cols-[1fr_2fr]">
      <header className="lg:sticky lg:top-10 lg:self-start">
        <p className="text-xs tracking-[0.2em] text-brand-text uppercase">{i18n.t("publicSite", "news")}</p>
        <h1 className="font-display mt-2 text-3xl leading-tight font-semibold tracking-tight text-balance">
          {article.title}
        </h1>
        <div className="mt-3">
          <ArticleDate article={article} site={site} />
        </div>
        <Link href="/news" className="mt-6 inline-block text-sm text-ink-muted hover:text-brand-text">
          ← {i18n.t("publicSite", "allNews")}
        </Link>
      </header>
      <div className="max-w-prose text-[15px]">
        <ArticleBody blocks={article.body} />
      </div>
    </article>
  );
}
