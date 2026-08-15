import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { siteTranslator } from "@/lib/i18n";
import { getArticle, getSite } from "@/lib/site";
import { templateFor } from "@/templates";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const article = await getArticle(slug);
  if (!article) return { title: "Not found" };
  return {
    title: article.seo_title ?? article.title,
    description: article.seo_description ?? article.excerpt ?? undefined,
    openGraph: {
      title: article.title,
      description: article.excerpt ?? undefined,
      type: "article",
      publishedTime: article.published_at ?? undefined,
    },
    alternates: { canonical: `/news/${article.slug}` },
  };
}

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const site = await getSite();
  if (!site) notFound();

  // A draft, scheduled or archived article is a 404 here — indistinguishable
  // from one that never existed.
  const article = await getArticle(slug);
  if (!article) notFound();

  const { ArticleView } = templateFor(site.branding.template);
  return <ArticleView site={site} article={article} i18n={await siteTranslator(site)} />;
}
