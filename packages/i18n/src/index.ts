import { en, type Catalogue } from "./catalogue";
import { ro } from "./ro";

export type { Catalogue };
export { en, ro };

/**
 * Translation.
 *
 * Small on purpose. A club admin needs the interface in the club's language;
 * it does not need runtime message compilation, ICU syntax or a 40KB library
 * that has to be initialised before the first paint.
 *
 * The pieces that do matter and are here: compile-time key safety, correct
 * plurals for the languages we ship, and dates and numbers formatted by the
 * platform's own `Intl` rather than by hand.
 */

export const LOCALES = [
  { code: "en", endonym: "English", englishName: "English" },
  { code: "ro", endonym: "Română", englishName: "Romanian" },
] as const;

export type LocaleCode = (typeof LOCALES)[number]["code"];

export const DEFAULT_LOCALE: LocaleCode = "en";

const CATALOGUES: Record<LocaleCode, Catalogue> = { en, ro };

export function isLocale(value: string): value is LocaleCode {
  return LOCALES.some((locale) => locale.code === value);
}

/** Fold `ro-RO`, `RO` and `ro` onto a locale we ship. */
export function normaliseLocale(value: string | null | undefined): LocaleCode {
  const base = (value ?? "").trim().toLowerCase().replace("_", "-").split("-")[0] ?? "";
  return isLocale(base) ? base : DEFAULT_LOCALE;
}

/* --- message lookup -------------------------------------------------------- */

type Section = keyof Catalogue;

function interpolate(message: string, values?: Record<string, string | number>): string {
  if (!values) return message;
  return message.replace(/\{(\w+)\}/g, (whole, key: string) =>
    key in values ? String(values[key]) : whole,
  );
}

export interface Translator {
  locale: LocaleCode;
  /** `t("nav", "players")`, or with values: `t("workspace", "chooseSubtitle", { email })`. */
  t: <S extends Section, K extends keyof Catalogue[S]>(
    section: S,
    key: K,
    values?: Record<string, string | number>,
  ) => string;
  /** Chooses between `<key>_one` and `<key>_other` by the locale's own rule. */
  plural: <S extends Section>(section: S, key: string, count: number) => string;
  formatNumber: (value: number) => string;
  formatDate: (value: string | Date, options?: Intl.DateTimeFormatOptions) => string;
  /** "today", "yesterday", "3 days ago" — the granularity a club actually reads. */
  formatRelativeDay: (value: string | Date | null) => string;
}

/**
 * Romanian has three plural forms, not two: 1, then 2–19 and anything ending
 * 01–19 (CLDR's "few"), then the rest — which takes "de", as in "21 de
 * jucători". Keys are suffixed with the CLDR category itself (`_one`, `_few`,
 * `_other`) and fall back to `_other`, so a catalogue only spells out the
 * forms it actually needs: English never selects "few" and never writes one,
 * and a Romanian noun that is never counted past nineteen does not either.
 */
const PLURAL_RULES: Record<LocaleCode, Intl.PluralRules> = {
  en: new Intl.PluralRules("en"),
  ro: new Intl.PluralRules("ro"),
};

export function createTranslator(locale: LocaleCode): Translator {
  const catalogue = CATALOGUES[locale] ?? en;
  const fallback = en;

  const lookup = (section: Section, key: string): string | undefined => {
    const fromLocale = (catalogue[section] as Record<string, string>)[key];
    if (typeof fromLocale === "string") return fromLocale;
    // A missing key cannot happen — the catalogues are typed against each
    // other — but a locale added at runtime could still miss one, and showing
    // the English word beats showing a key.
    const fromEnglish = (fallback[section] as Record<string, string>)[key];
    return typeof fromEnglish === "string" ? fromEnglish : undefined;
  };

  return {
    locale,

    t: (section, key, values) =>
      interpolate(lookup(section, String(key)) ?? `${String(section)}.${String(key)}`, values),

    plural: (section, key, count) => {
      const category = PLURAL_RULES[locale].select(count);
      return interpolate(
        lookup(section, `${key}_${category}`) ??
          lookup(section, `${key}_other`) ??
          `${String(section)}.${key}`,
        { count },
      );
    },

    formatNumber: (value) => new Intl.NumberFormat(locale).format(value),

    formatDate: (value, options) =>
      new Intl.DateTimeFormat(locale, options ?? {
        day: "numeric",
        month: "short",
        year: "numeric",
      }).format(typeof value === "string" ? new Date(value) : value),

    formatRelativeDay: (value) => {
      if (!value) return "—";
      const date = typeof value === "string" ? new Date(value) : value;
      const days = Math.round((Date.now() - date.getTime()) / 86_400_000);
      const dash = CATALOGUES[locale] ?? en;
      if (days === 0) return dash.dashboard.today;
      if (days === 1) return dash.dashboard.yesterday;
      if (days < 30) return interpolate(dash.dashboard.daysAgo, { count: days });
      return new Intl.DateTimeFormat(locale, {
        day: "numeric",
        month: "short",
      }).format(date);
    },
  };
}
