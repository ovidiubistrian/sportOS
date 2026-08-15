import type { ClubHistory } from "@/lib/site";
import { SectionHeading } from "./section";

/**
 * The club's record: where it finished, season by season.
 *
 * A table rather than a chart. Supporters read this to settle arguments —
 * "what did we do the year we went down?" — and a column of positions answers
 * that faster than a shape does.
 *
 * The palmarès is derived from first places, not typed in, because the
 * provider has no honours endpoint and a claim nobody can check is worse than
 * an empty section that will fill itself the season they win something.
 */

export interface HistoryLabels {
  title: string;
  lead: string;
  season: string;
  competition: string;
  position: string;
  played: string;
  record: string;
  points: string;
  honours: string;
  founded: string;
  ground: string;
  capacity: string;
}

export function ClubRecord({
  history,
  labels,
  locale,
}: {
  history: ClubHistory;
  labels: HistoryLabels;
  locale: string;
}) {
  const facts = [
    history.founded_year && { label: labels.founded, value: String(history.founded_year) },
    history.venue_name && { label: labels.ground, value: history.venue_name },
    history.venue_capacity && {
      label: labels.capacity,
      value: new Intl.NumberFormat(locale).format(history.venue_capacity),
    },
  ].filter(Boolean) as { label: string; value: string }[];

  if (facts.length === 0 && history.seasons.length === 0) return null;

  return (
    <section className="mx-auto max-w-6xl px-6 py-14">
      <SectionHeading title={labels.title} lead={labels.lead} />

      {facts.length > 0 && (
        <div className="mb-8 grid gap-px overflow-hidden rounded-xl border border-rule bg-rule sm:grid-cols-3">
          {facts.map((fact) => (
            <div key={fact.label} className="bg-page p-5">
              <p className="text-[11px] tracking-[0.12em] text-ink-faint uppercase">
                {fact.label}
              </p>
              <p className="font-display mt-1.5 text-2xl font-extrabold tracking-tight">
                {fact.value}
              </p>
            </div>
          ))}
        </div>
      )}

      {history.honours.length > 0 && (
        <div className="mb-8">
          <p className="mb-3 text-[11px] tracking-[0.12em] text-ink-faint uppercase">
            {labels.honours}
          </p>
          <ul className="flex flex-wrap gap-2">
            {history.honours.map((honour) => (
              <li
                key={honour}
                className="rounded-full px-3.5 py-1.5 text-xs font-semibold"
                style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
              >
                {honour}
              </li>
            ))}
          </ul>
        </div>
      )}

      {history.seasons.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-rule">
          <table className="tabular w-full min-w-[38rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-rule text-left text-xs text-ink-muted">
                <th className="py-3 pl-4 font-medium">{labels.season}</th>
                <th className="py-3 font-medium">{labels.competition}</th>
                <th className="px-3 py-3 text-center font-medium">{labels.position}</th>
                <th className="px-3 py-3 text-center font-medium">{labels.played}</th>
                <th className="px-3 py-3 text-center font-medium">{labels.record}</th>
                <th className="px-3 py-3 pr-4 text-center font-medium">{labels.points}</th>
              </tr>
            </thead>
            <tbody>
              {history.seasons.map((row) => (
                <tr
                  key={`${row.season}-${row.competition}`}
                  className="border-b border-rule last:border-0"
                >
                  <td className="py-3 pl-4 font-semibold">{row.season}</td>
                  <td className="py-3">
                    <span className="block">{row.competition}</span>
                    {row.outcome && (
                      <span className="mt-0.5 block text-xs text-ink-faint">
                        {row.outcome}
                      </span>
                    )}
                  </td>
                  <td
                    className="px-3 py-3 text-center font-bold"
                    style={row.position === 1 ? { color: "var(--brand)" } : undefined}
                  >
                    {row.position ?? "—"}
                  </td>
                  <td className="px-3 py-3 text-center text-ink-muted">{row.played}</td>
                  <td className="px-3 py-3 text-center text-ink-muted">
                    {row.won}–{row.drawn}–{row.lost}
                  </td>
                  <td className="px-3 py-3 pr-4 text-center font-semibold">{row.points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
