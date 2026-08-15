import { createTranslator, normaliseLocale, type Translator } from "@footbola/i18n";
import { cookies, headers } from "next/headers";

import type { Site } from "./site";

/**
 * What language a club's website is read in.
 *
 * Resolved in the order that respects who decided what:
 *
 *   1. the reader's explicit choice, if they picked one from the switcher;
 *   2. their browser's `Accept-Language`, if the club publishes in it;
 *   3. the club's own default.
 *
 * A supporter's browser already says what they read. Ignoring it and serving
 * the club's language to everyone is the thing that makes a bilingual club's
 * site feel like it was built for one half of its supporters.
 *
 * Only languages the club actually publishes in are offered — falling back to
 * a platform language the club has never written a word in would be worse than
 * showing them the one it has.
 */

const CHOICE_COOKIE = "fos_locale";

export async function preferredLocale(site: Site): Promise<string> {
  const supported = site.locales.length > 0 ? site.locales : [site.locale];

  const chosen = (await cookies()).get(CHOICE_COOKIE)?.value;
  if (chosen && supported.includes(chosen)) return chosen;

  const accept = (await headers()).get("accept-language") ?? "";
  for (const part of accept.split(",")) {
    const tag = part.split(";")[0]?.trim().toLowerCase() ?? "";
    const base = tag.split("-")[0] ?? "";
    if (base && supported.includes(base)) return base;
  }

  return site.locale;
}

/** The site's chrome, in the reader's language. */
export async function siteTranslator(site: Site): Promise<Translator> {
  return createTranslator(normaliseLocale(await preferredLocale(site)));
}

export { CHOICE_COOKIE };
