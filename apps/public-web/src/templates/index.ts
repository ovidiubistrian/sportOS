import type { Translator } from "@footbola/i18n";
import type { ComponentType, ReactNode } from "react";

import type { SiteTemplate } from "@/lib/site";
import * as bold from "./bold";
import * as classic from "./classic";
import * as compact from "./compact";
import * as editorial from "./editorial";
import type {
  ArticleViewProps,
  NewsListProps,
  TeamViewProps,
  TemplateProps,
} from "./shared";

/**
 * Template registry.
 *
 * Four presentations of one content model. Adding a template means adding a
 * module and one entry here — routes, data fetching and the API are untouched,
 * which is the whole reason templates are a component set rather than four
 * applications.
 */

export interface TemplateModule {
  Shell: ComponentType<{
    site: TemplateProps["site"];
    children: ReactNode;
    // The reader's language, resolved once per request in the layout.
    i18n: Translator;
  }>;
  TeamView: ComponentType<TeamViewProps>;
  NewsList: ComponentType<NewsListProps>;
  ArticleView: ComponentType<ArticleViewProps>;
}

const TEMPLATES: Record<SiteTemplate, TemplateModule> = {
  CLASSIC: classic,
  BOLD: bold,
  COMPACT: compact,
  EDITORIAL: editorial,
};

export function templateFor(name: string | undefined): TemplateModule {
  // An unknown value means a template was removed while a club still points at
  // it. Falling back keeps the site up rather than 500ing on a data problem.
  return TEMPLATES[(name ?? "CLASSIC") as SiteTemplate] ?? TEMPLATES.CLASSIC;
}

export const TEMPLATE_NAMES = Object.keys(TEMPLATES) as SiteTemplate[];
