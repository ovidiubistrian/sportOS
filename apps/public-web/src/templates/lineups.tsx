import type { Translator } from "@footbola/i18n";
import type { LineupPlayer, MatchLineup, PublicMatch } from "@/lib/site";

/**
 * The two team sheets, under the scoreboard.
 *
 * Renders nothing at all until a sheet exists. The provider publishes one
 * about an hour before kick-off — and for a league it does not cover fully,
 * sometimes not until after the final whistle — so an empty block would be the
 * normal state of this component for most of a season. A section that is
 * usually an empty heading teaches a supporter to stop looking at it.
 *
 * **The list, not the pitch, is the default.** For most leagues the provider
 * gives names and shirt numbers and no positions at all, so a pitch would have
 * to invent where people stand. `PITCH` is opt-in per club, and even then this
 * falls back to the list when nobody has arranged the eleven — which is the
 * honest thing to do and also what happens on its own, since the arrangement
 * lives in `grid` and `grid` is null until somebody sets it.
 */

function Player({ player }: { player: LineupPlayer }) {
  return (
    <li className="flex items-baseline gap-2.5 py-1 text-sm">
      <span
        className="w-6 shrink-0 text-right text-xs tabular-nums text-ink-faint"
        aria-hidden={player.shirt_number == null}
      >
        {player.shirt_number ?? ""}
      </span>
      <span className="min-w-0 truncate">{player.name}</span>
    </li>
  );
}

function Side({
  lineup,
  name,
  i18n,
}: {
  lineup: MatchLineup;
  name: string;
  i18n: Translator;
}) {
  return (
    <div className="min-w-0">
      <h3 className="font-display text-sm font-bold">{name}</h3>
      {lineup.formation && (
        <p className="mt-0.5 text-xs tabular-nums text-ink-muted">{lineup.formation}</p>
      )}

      <ul className="mt-3">
        {lineup.starters.map((player, index) => (
          <Player key={`${player.name}-${index}`} player={player} />
        ))}
      </ul>

      {lineup.substitutes.length > 0 && (
        <>
          <h4 className="mt-4 text-[10px] font-bold tracking-[0.18em] uppercase text-ink-faint">
            {i18n.t("publicSite", "lineupSubstitutes")}
          </h4>
          <ul className="mt-1.5">
            {lineup.substitutes.map((player, index) => (
              <Player key={`${player.name}-${index}`} player={player} />
            ))}
          </ul>
        </>
      )}

      {lineup.coach_name && (
        <p className="mt-4 text-xs text-ink-muted">
          {i18n.t("publicSite", "lineupCoach")}: {lineup.coach_name}
        </p>
      )}
    </div>
  );
}

export function Lineups({ match, i18n }: { match: PublicMatch; i18n: Translator }) {
  const home = match.home_lineup;
  const away = match.away_lineup;
  if (!home && !away) return null;

  return (
    <section className="mx-auto max-w-4xl px-6 py-10">
      <h2 className="font-display text-[11px] font-bold tracking-[0.2em] uppercase text-ink-muted">
        {i18n.t("publicSite", "lineupTitle")}
      </h2>

      <div className="mt-5 grid gap-8 sm:grid-cols-2">
        {home && <Side lineup={home} name={match.home.name} i18n={i18n} />}
        {away && <Side lineup={away} name={match.away.name} i18n={i18n} />}
      </div>
    </section>
  );
}
