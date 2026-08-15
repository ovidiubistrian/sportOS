/**
 * Prices, in minor units.
 *
 * The API speaks integers — 1250, not 12.50 — because a float price is a
 * rounding error somebody eventually has to refund. Humans type decimals, so
 * the conversion happens here, once, rather than in each form that touches a
 * price.
 *
 * The exponent comes from the currency, not from a constant: JPY has none and
 * would be a hundred times wrong under a hardcoded 2.
 */

const EXPONENTS: Record<string, number> = {
  JPY: 0,
  KRW: 0,
  ISK: 0,
  HUF: 0,
  CLP: 0,
  VND: 0,
  BHD: 3,
  KWD: 3,
  OMR: 3,
  TND: 3,
};

export function exponentFor(currency: string): number {
  return EXPONENTS[currency.toUpperCase()] ?? 2;
}

/** Minor units to what goes in a text field: 1250 → "12.50". */
export function minorToInput(minor: number, currency: string): string {
  const exponent = exponentFor(currency);
  if (exponent === 0) return String(minor);
  return (minor / 10 ** exponent).toFixed(exponent);
}

/**
 * What the user typed, back to minor units. `null` means "not a price yet",
 * which the form uses to keep Save disabled rather than to show an error at
 * someone still typing.
 */
export function parsePrice(value: string, currency: string): number | null {
  const cleaned = value.trim().replace(",", ".");
  if (!cleaned) return null;
  if (!/^\d+(\.\d+)?$/.test(cleaned)) return null;

  const exponent = exponentFor(currency);
  // Scale as a string then round, rather than `parseFloat * 100` — 19.99 * 100
  // is 1998.9999999999998, and floor would charge a cent less.
  return Math.round(Number(cleaned) * 10 ** exponent);
}

/** For display: 1250 EUR → "12,50 €" in the reader's own locale. */
export function formatMoney(minor: number, currency: string, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
  }).format(minor / 10 ** exponentFor(currency));
}
