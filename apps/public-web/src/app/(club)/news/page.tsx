import { notFound } from "next/navigation";

import { siteTranslator } from "@/lib/i18n";
import { getNews, getSite } from "@/lib/site";
import { templateFor } from "@/templates";

export const metadata = { title: "News" };

export default async function NewsPage() {
  const site = await getSite();
  if (!site) notFound();

  const articles = await getNews(20);
  const { NewsList } = templateFor(site.branding.template);
  return <NewsList site={site} articles={articles} i18n={await siteTranslator(site)} />;
}
