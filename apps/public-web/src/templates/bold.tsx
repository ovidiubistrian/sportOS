import { SiteFooter } from "./footer";
import { MobileNav } from "./mobile-nav";
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
  PageHeader,
  SquadTable,
  type ArticleViewProps,
  type NewsListProps,
  type TeamViewProps,
  type TemplateProps,
} from "./shared";

/**
 * BOLD — the modern professional club.
 *
 * Editorial rather than branded: quiet chrome, very large tight headlines, and
 * the club's colour spent on the few things a supporter is meant to act on.
 *
 * It used to put the brand colour on the header, the footer and every page
 * header as full-bleed slabs. That reads as a brand guideline rather than as a
 * design, and it was worst exactly where there was least to say — the shop
 * header filled half the first screen with saturation above three words. The
 * colour is still everywhere it counts: the crest, the calls to action, the
 * eyebrow over every page title. See `globals.css` for the full reasoning.
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
      {/* Translucent, so a hero photograph carries on under it while the nav
          stays readable over whatever happens to be scrolling past. */}
      <header className="sticky top-0 z-20 border-b border-rule bg-page/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-6">
          <Link href="/" className="flex shrink-0 items-center gap-2.5">
            <Crest site={site} size={28} />
            <span className="font-display text-sm font-extrabold tracking-tight uppercase">
              {site.short_name}
            </span>
          </Link>
          <div className="flex items-center gap-6">
            {/* Hidden rather than wrapped below `md`: five links, a crest and
                an account button do not fit across a phone, and the row used to
                push the whole page wider than the screen instead of giving
                way. */}
            <nav aria-label="Main" className="hidden md:block">
              <ul className="flex gap-7">
                {NAV.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="text-[13px] font-medium text-ink-muted transition-colors hover:text-ink"
                    >
                      {i18n.t("publicSite", item.key)}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
            <AccountLink label={i18n.t("publicSite", "accountNav")} />
            <MobileNav
              items={NAV.map((item) => ({
                href: item.href,
                label: i18n.t("publicSite", item.key),
              }))}
              openLabel={i18n.t("publicSite", "menuOpen")}
              closeLabel={i18n.t("publicSite", "menuClose")}
            />
          </div>
        </div>
      </header>

      {children}

      <footer className="mt-24 bg-surface-deep text-surface-deep-ink">
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
      <PageHeader
        eyebrow={i18n.t("publicSite", team.is_academy ? "academy" : "senior")}
        title={team.name}
      />
      <main className="mx-auto max-w-6xl px-6 py-12">
        <SquadTable squad={squad} emptyLabel={i18n.t("publicSite", "squadUnpublished")} />
        <Link
          href="/teams"
          className="mt-10 inline-block text-sm font-semibold text-brand-text underline-offset-4 hover:underline"
        >
          ← {i18n.t("publicSite", "ourTeams")}
        </Link>
      </main>
    </>
  );
}


export function NewsList({ site, i18n, articles }: NewsListProps) {
  return (
    <>
      <PageHeader eyebrow={site.short_name} title={i18n.t("publicSite", "news")} />
      <main className="mx-auto max-w-6xl px-6 py-12">
        {articles.length === 0 ? (
          <NewsEmpty />
        ) : (
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {articles.map((article) => (
              <Link
                key={article.id}
                href={`/news/${article.slug}`}
                className="group flex flex-col overflow-hidden rounded-xl border border-rule transition-all duration-200 hover:-translate-y-0.5 hover:border-rule-strong hover:shadow-[0_14px_32px_-22px_rgb(0_0_0/0.4)]"
              >
                {/* This article's own picture, or the crest faintly. Never the
                    club's home page image: on a list, a borrowed photograph is
                    indistinguishable from a chosen one. */}
                <div className="relative grid aspect-[16/10] place-items-center overflow-hidden bg-page-alt">
                  {article.cover_url ? (
                    <img
                      src={article.cover_url}
                      alt=""
                      loading="lazy"
                      style={{ objectPosition: article.cover_focus ?? undefined }}
                      className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.04]"
                    />
                  ) : (
                    <span aria-hidden className="opacity-25 grayscale">
                      <Crest site={site} size={44} />
                    </span>
                  )}
                  {article.is_pinned && (
                    <span
                      className="absolute top-3 left-3 rounded-full px-2.5 py-1 text-[10px] font-bold tracking-[0.14em] uppercase"
                      style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
                    >
                      Featured
                    </span>
                  )}
                </div>

                <div className="flex flex-1 flex-col p-6">
                  <h2 className="font-display text-xl leading-tight font-extrabold tracking-tight text-balance transition-colors group-hover:text-brand-text">
                    {article.title}
                  </h2>
                  {article.excerpt && (
                    <p className="mt-2.5 line-clamp-3 flex-1 text-sm/relaxed text-ink-muted">
                      {article.excerpt}
                    </p>
                  )}
                  <div className="mt-5">
                    <ArticleDate article={article} site={site} />
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </>
  );
}

export function ArticleView({ site, i18n, article }: ArticleViewProps) {
  return (
    <>
      {/* Narrower than the other page headers: this one sits directly over a
          column of body text and has to line up with it. */}
      <header className="border-b border-rule">
        <div className="mx-auto max-w-3xl px-6 pt-14 pb-10 sm:pt-20">
          <p
            className="text-[11px] font-bold tracking-[0.18em] uppercase"
            style={{ color: "var(--brand-text)" }}
          >
            {i18n.t("publicSite", "news")}
          </p>
          <h1 className="font-display mt-3 text-[clamp(1.875rem,4.5vw,3rem)] leading-[1.05] font-extrabold tracking-[-0.03em] text-balance">
            {article.title}
          </h1>
          {article.published_at && (
            <p className="mt-4 text-sm text-ink-muted">
              {formatDate(article.published_at, site)}
            </p>
          )}
        </div>
      </header>
      {/* The picture the club chose for this story, at the top of the story.
          It was being shown on the card that links here and then nowhere on
          the page itself, which reads as the photograph having been lost on
          the way in. Cropped around the focal point, like every other frame. */}
      {article.cover_url && (
        <figure className="mx-auto max-w-4xl px-6 pt-10">
          <img
            src={article.cover_url}
            alt={article.title}
            className="aspect-[16/9] w-full rounded-xl object-cover"
            style={{ objectPosition: article.cover_focus ?? undefined }}
            loading="eager"
            fetchPriority="high"
          />
        </figure>
      )}
      <main className="mx-auto max-w-2xl px-6 py-12 text-[16px]/relaxed">
        <ArticleBody blocks={article.body} />
        <Link
          href="/news"
          className="mt-12 inline-block text-sm font-semibold text-brand-text underline-offset-4 hover:underline"
        >
          ← {i18n.t("publicSite", "allNews")}
        </Link>
      </main>
    </>
  );
}
