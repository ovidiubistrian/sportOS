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
 * COMPACT — information first.
 *
 * Narrow measure, small type, a sidebar on desktop, no hero and no imagery.
 * Built for the club that has 14 academy teams and no photographer: it looks
 * complete with nothing but names and numbers, loads on a poor connection, and
 * gets a parent to the fixture they came for in one click. Brand colour is a
 * thin accent only.
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
      <div className="mx-auto flex max-w-4xl gap-8 px-5 py-6 lg:py-10">
        <aside className="hidden w-40 shrink-0 lg:block">
          <div className="sticky top-10 space-y-5">
            <Link href="/" className="flex items-center gap-2">
              <Crest site={site} size={28} />
              <span className="text-sm leading-tight font-semibold">{site.short_name}</span>
            </Link>
            <nav aria-label="Main">
              <ul className="space-y-1">
                {NAV.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="block border-l-2 border-transparent py-1 pl-2 text-sm text-ink-muted hover:border-[var(--brand)] hover:text-ink"
                    >
                      {i18n.t("publicSite", item.key)}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
            <div className="mt-6">
              <AccountLink
                label={i18n.t("publicSite", "accountNav")}
              />
            </div>
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="mb-6 flex items-center justify-between gap-3 border-b border-rule pb-4 lg:hidden">
            <Link href="/" className="flex items-center gap-2">
              <Crest site={site} size={26} />
              <span className="text-sm font-semibold">{site.short_name}</span>
            </Link>
            <nav aria-label="Main">
              <ul className="flex gap-4">
                {NAV.map((item) => (
                  <li key={item.href}>
                    <Link href={item.href} className="text-xs text-ink-muted hover:text-ink">
                      {i18n.t("publicSite", item.key)}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </header>

          {children}

          <footer className="mt-12 flex items-center justify-between gap-4 border-t border-rule pt-4 text-xs text-ink-faint">
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
      </div>
    </div>
  );
}

export function TeamView({ i18n, team, squad }: TeamViewProps) {
  return (
    <>
      <div className="mb-5">
        <Link href="/teams" className="text-xs text-ink-muted hover:text-ink">
          ← Teams
        </Link>
        <h1 className="mt-1 text-lg font-semibold tracking-tight">{team.name}</h1>
        <p className="tabular text-xs text-ink-faint">
          {i18n.plural("publicSite", "playerCount", squad.length)} · {team.is_academy ? "academy" : "senior"}
        </p>
      </div>
      <SquadTable squad={squad} emptyLabel={i18n.t("publicSite", "squadUnpublished")} />
    </>
  );
}


export function NewsList({ site, i18n, articles }: NewsListProps) {
  return (
    <>
      <h1 className="mb-4 text-lg font-semibold tracking-tight">{i18n.t("publicSite", "news")}</h1>
      {articles.length === 0 ? (
        <NewsEmpty />
      ) : (
        <ul className="divide-y divide-rule border-y border-rule">
          {articles.map((article) => (
            <li key={article.id}>
              <Link href={`/news/${article.slug}`} className="block py-2.5 hover:text-brand-text">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm font-medium">{article.title}</span>
                  <ArticleDate article={article} site={site} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function ArticleView({ site, i18n, article }: ArticleViewProps) {
  return (
    <article className="max-w-prose">
      <Link href="/news" className="text-xs text-ink-muted hover:text-ink">
        ← {i18n.t("publicSite", "news")}
      </Link>
      <h1 className="mt-1 text-lg font-semibold tracking-tight text-balance">
        {article.title}
      </h1>
      <div className="mt-0.5 mb-5">
        <ArticleDate article={article} site={site} />
      </div>
      <div className="text-sm">
        <ArticleBody blocks={article.body} />
      </div>
    </article>
  );
}
