import type { PublicMatch } from "./site";

/**
 * How a round reads to a supporter.
 *
 * A numbered league round is labelled in the reader's language; a named cup
 * round is already a name and is shown as it is. The two are separate fields
 * because they are separate things — the server used to concatenate them into
 * Romanian prose, which every English club then read in Romanian.
 */
export function roundLabel(match: PublicMatch, matchday: string): string | null {
  if (match.round_number != null) return `${matchday} ${match.round_number}`;
  return match.round_label;
}
