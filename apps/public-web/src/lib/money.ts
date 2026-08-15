/**
 * Money formatting, in its own module.
 *
 * Deliberately not in `lib/site.ts`: that reads `next/headers` at module scope,
 * so a client component importing a *value* from it drags server-only code into
 * the browser bundle and the build fails. Types are erased and would have been
 * fine; a function is not.
 */
export function formatMoney(minor: number, currency: string, locale: string): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(
    minor / 100,
  );
}
