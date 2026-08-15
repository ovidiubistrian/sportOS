import type { MatchEvent, PublicMatch } from "@/lib/site";

/**
 * What happened in a match.
 *
 * Two columns split down a centre line, home on the left and away on the
 * right, because that is how a supporter already reads a scoreboard and it
 * makes "who is winning the second half" answerable at a glance.
 *
 * Substitutions are deliberately quieter than goals: a match report where a
 * 63rd-minute change is as loud as an equaliser is a log, not a story.
 */

export interface EventLabels {
  goal: string;
  ownGoal: string;
  penalty: string;
  missedPenalty: string;
  yellow: string;
  red: string;
  substitution: string;
}

function icon(event: MatchEvent): string {
  const detail = (event.detail ?? "").toLowerCase();
  if (event.kind === "GOAL") {
    if (detail.includes("own")) return "⚽";
    if (detail.includes("missed")) return "✗";
    return "⚽";
  }
  if (event.kind === "CARD") return detail.includes("red") ? "🟥" : "🟨";
  if (event.kind === "SUBSTITUTION") return "⇄";
  return "•";
}

function describe(event: MatchEvent, labels: EventLabels): string {
  const detail = (event.detail ?? "").toLowerCase();
  if (event.kind === "GOAL") {
    if (detail.includes("own")) return labels.ownGoal;
    if (detail.includes("missed")) return labels.missedPenalty;
    if (detail.includes("penalty")) return labels.penalty;
    return labels.goal;
  }
  if (event.kind === "CARD") {
    return detail.includes("red") ? labels.red : labels.yellow;
  }
  if (event.kind === "SUBSTITUTION") return labels.substitution;
  return event.detail ?? "";
}

function Row({ event, labels }: { event: MatchEvent; labels: EventLabels }) {
  const quiet = event.kind === "SUBSTITUTION";
  const body = (
    <div
      className={
        event.is_home
          ? "flex items-baseline justify-end gap-2 text-right"
          : "flex items-baseline gap-2"
      }
    >
      {event.is_home && (
        <span className="text-xs text-ink-faint">{describe(event, labels)}</span>
      )}
      <span className={quiet ? "text-sm text-ink-muted" : "text-sm font-semibold"}>
        {event.player_name ?? "—"}
      </span>
      {!event.is_home && (
        <span className="text-xs text-ink-faint">{describe(event, labels)}</span>
      )}
    </div>
  );

  return (
    <li className="grid grid-cols-[1fr_3.5rem_1fr] items-baseline gap-2 py-2">
      <div>{event.is_home ? body : null}</div>
      <div className="flex items-baseline justify-center gap-1.5">
        <span aria-hidden className={quiet ? "text-xs opacity-60" : "text-sm"}>
          {icon(event)}
        </span>
        <span className="tabular text-xs font-semibold text-ink-muted">
          {event.minute ?? "—"}
          {event.extra_minute ? `+${event.extra_minute}` : ""}&apos;
        </span>
      </div>
      <div>{event.is_home ? null : body}</div>
    </li>
  );
}

export function MatchTimeline({
  match,
  labels,
  title,
}: {
  match: PublicMatch;
  labels: EventLabels;
  title: string;
}) {
  if (match.events.length === 0) return null;

  return (
    <section className="mx-auto max-w-3xl px-6 py-10">
      <h3 className="font-display mb-4 text-center text-xs font-bold tracking-[0.2em] text-ink-muted uppercase">
        {title}
      </h3>
      <ul className="divide-y divide-rule border-y border-rule">
        {match.events.map((event, index) => (
          <Row key={`${event.minute}-${event.kind}-${index}`} event={event} labels={labels} />
        ))}
      </ul>
    </section>
  );
}

/** Just the scorers, for the scoreboard. */
export function Scorers({ match }: { match: PublicMatch }) {
  const goals = match.events.filter(
    (event) => event.kind === "GOAL" && !(event.detail ?? "").toLowerCase().includes("missed"),
  );
  if (goals.length === 0) return null;

  const side = (home: boolean) =>
    goals
      .filter((goal) => goal.is_home === home)
      .map((goal) => `${goal.player_name ?? "—"} ${goal.minute ?? ""}'`)
      .join(", ");

  return (
    <div className="grid grid-cols-[1fr_auto_1fr] gap-4 text-xs opacity-85">
      <p className="text-right">{side(true)}</p>
      <span aria-hidden>⚽</span>
      <p>{side(false)}</p>
    </div>
  );
}
