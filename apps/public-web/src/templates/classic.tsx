import { SiteFooter } from "./footer";
import type { Translator } from "@footbola/i18n";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  ArticleBody,
  ArticleDate,
  Crest,
  Established,
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
 * CLASSIC — the traditional club site.
 *
 * Centred crest, horizontal rule under the masthead, content in bordered
 * blocks, squads as tables. Formal and quiet: it suits a club whose identity
 * is its history rather than its photography, and it looks correct with no
 * imagery at all. Brand colour appears as the masthead rule and heading
 * accents, never as a large fill.
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
      <div className="h-1 w-full" style={{ background: "var(--brand)" }} />

      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-5xl flex-col items-center gap-3 px-6 py-8 text-center">
          <Crest site={site} size={64} />
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">
              {site.name}
            </h1>
            {site.branding.tagline && (
              <p className="mt-1 text-sm text-ink-muted">{site.branding.tagline}</p>
            )}
          </div>
          <Established site={site} />
        </div>

        <nav
          aria-label="Main"
          className="flex items-center justify-center gap-8 border-t border-rule px-6"
        >
          <ul className="flex justify-center gap-8">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="block border-b-2 border-transparent py-3 text-sm font-medium tracking-wide uppercase hover:border-[var(--brand)] hover:text-brand-text"
                >
                  {i18n.t("publicSite", item.key)}
                </Link>
              </li>
            ))}
          </ul>
          <AccountLink
            label={i18n.t("publicSite", "accountNav")}
          />
        </nav>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>

      <footer className="border-t border-rule py-8">
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

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-4 border-b-2 pb-2 font-display text-lg font-bold tracking-tight" style={{ borderColor: "var(--brand)" }}>
      {children}
    </h2>
  );
}

export function TeamView({ i18n, team, squad }: TeamViewProps) {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs tracking-widest text-ink-muted uppercase">
          {i18n.t("publicSite", team.is_academy ? "academy" : "senior")}
        </p>
        <h2 className="font-display text-2xl font-bold tracking-tight">{team.name}</h2>
      </div>
      <SquadTable squad={squad} emptyLabel={i18n.t("publicSite", "squadUnpublished")} />
      <Link href="/teams" className="inline-block text-sm text-brand-text hover:underline">
        ← {i18n.t("publicSite", "ourTeams")}
      </Link>
    </div>
  );
}


export function NewsList({ site, i18n, articles }: NewsListProps) {
  return (
    <div className="space-y-6">
      <SectionHeading>{i18n.t("publicSite", "latestNews")}</SectionHeading>
      {articles.length === 0 ? (
        <NewsEmpty />
      ) : (
        <ul className="divide-y divide-rule border-y border-rule">
          {articles.map((article) => (
            <li key={article.id}>
              <Link href={`/news/${article.slug}`} className="block py-4 hover:bg-page-alt">
                <div className="flex items-baseline justify-between gap-4">
                  <h3 className="font-display font-semibold">{article.title}</h3>
                  <ArticleDate article={article} site={site} />
                </div>
                {article.excerpt && (
                  <p className="mt-1 text-sm text-ink-muted">{article.excerpt}</p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ArticleView({ site, i18n, article }: ArticleViewProps) {
  return (
    <article className="mx-auto max-w-2xl">
      <header className="border-b-2 pb-4" style={{ borderColor: "var(--brand)" }}>
        <ArticleDate article={article} site={site} />
        <h1 className="font-display mt-1 text-2xl font-bold tracking-tight text-balance">
          {article.title}
        </h1>
      </header>
      <div className="pt-6">
        <ArticleBody blocks={article.body} />
      </div>
      <Link href="/news" className="mt-8 inline-block text-sm text-brand-text hover:underline">
        ← {i18n.t("publicSite", "allNews")}
      </Link>
    </article>
  );
}
