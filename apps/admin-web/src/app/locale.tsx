import {
  DEFAULT_LOCALE,
  createTranslator,
  isLocale,
  normaliseLocale,
  type LocaleCode,
  type Translator,
} from "@footbola/i18n";
import { createContext, useContext, useMemo, type ReactNode } from "react";

/**
 * What language this admin is in.
 *
 * Resolved in the order that respects who decided what:
 *
 *   1. the person's own choice, if they made one;
 *   2. their browser's language, if we ship it;
 *   3. the tenant's language, chosen when the club was onboarded;
 *   4. English.
 *
 * The browser comes before the tenant because it is the one signal the person
 * has already given deliberately, on their own device. A Romanian volunteer at
 * a club that onboarded in English should not have to find a switcher, and an
 * English-speaking coach at a Romanian club should not be stuck in Romanian.
 * The tenant's language remains the fallback for anyone whose browser says
 * something we do not ship.
 *
 * Deliberately separate from the *content* languages. A club can publish its
 * website in three languages while its staff work in one.
 */

const OVERRIDE_KEY = "footbola.locale";

interface LocaleState extends Translator {
  /** Null when following the tenant. */
  override: LocaleCode | null;
  tenantLocale: LocaleCode;
  setOverride: (locale: LocaleCode | null) => void;
}

const LocaleContext = createContext<LocaleState | null>(null);

/** The first of the browser's languages we actually ship, or nothing. */
function browserLocale(): LocaleCode | null {
  for (const tag of navigator.languages ?? [navigator.language]) {
    const base = (tag ?? "").toLowerCase().split("-")[0] ?? "";
    if (isLocale(base)) return base;
  }
  return null;
}

function readOverride(): LocaleCode | null {
  const stored = window.localStorage.getItem(OVERRIDE_KEY);
  if (!stored) return null;
  const normalised = normaliseLocale(stored);
  return normalised === DEFAULT_LOCALE && stored !== DEFAULT_LOCALE ? null : normalised;
}

export function LocaleProvider({
  tenantLocale,
  children,
}: {
  tenantLocale: string | null | undefined;
  children: ReactNode;
}) {
  const resolvedTenant = normaliseLocale(tenantLocale);
  const override = readOverride();
  const fromBrowser = browserLocale();
  const active = override ?? fromBrowser ?? resolvedTenant;

  const value = useMemo<LocaleState>(() => {
    const translator = createTranslator(active);
    return {
      ...translator,
      override,
      tenantLocale: resolvedTenant,
      setOverride: (locale) => {
        if (locale === null) window.localStorage.removeItem(OVERRIDE_KEY);
        else window.localStorage.setItem(OVERRIDE_KEY, locale);
        // A full reload rather than a re-render: the locale reaches formatters,
        // `document.documentElement.lang` and every cached query key, and
        // reloading is both simpler and more honest than trying to thread it
        // through by hand.
        window.location.reload();
      },
    };
  }, [active, override, resolvedTenant]);

  // Screen readers switch voice on this, and it is what makes `:lang()` and
  // hyphenation behave.
  document.documentElement.lang = active;

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useI18n(): LocaleState {
  const state = useContext(LocaleContext);
  if (!state) throw new Error("useI18n must be used inside a <LocaleProvider>");
  return state;
}
