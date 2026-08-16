import Link from "next/link";

import type { Site, SquadPlayer, Team, TeamStaffMember } from "@/lib/site";

import { Crest } from "./shared";

/**
 * How a club presents its teams.
 *
 * The old version was a list of names in boxes, which is a database table with
 * rounded corners: it told a supporter that the club has a team called U15 and
 * nothing else. A club's teams page is a shop window — the first team is the
 * headline act and the academy is the club's future, and both should look like
 * somebody chose to show them.
 *
 * So: a hero that names the page and answers the three counting questions in
 * the same breath, the first team given the space of a feature with actual
 * faces on it, and the academy as a run of cards rather than a run of chips.
 *
 * Composed here rather than per template, like the front page. The four
 * templates differ in chrome and density; they were never going to differ in
 * *what a squad is*, and four copies of this only meant three of them rotted.
 */

export interface SquadLabels {
  title: string;
  lead: string;
  firstTeam: string;
  senior: string;
  academy: string;
  academyGroups: string;
  teams: string;
  players: string;
  viewSquad: string;
  squad: string;
  squadComingSoon: string;
  playerCount: (count: number) => string;
  /** The club's word for a staff role, in the reader's language. */
  staffRole: (role: string) => string;
}

/** Who may stand in for the head coach. A president may not. */
const COACHING_ROLES = new Set([
  "HEAD_COACH",
  "ASSISTANT_COACH",
  "GOALKEEPING_COACH",
  "FITNESS_COACH",
]);

function faces(roster: SquadPlayer[]): SquadPlayer[] {
  return roster.filter((player) => player.photo_url);
}

/** The hero. Photo when the club has one, its colour when it does not. */
function Hero({
  site,
  labels,
  stats,
}: {
  site: Site;
  labels: SquadLabels;
  stats: [string, string][];
}) {
  return (
    <section
      className="relative isolate overflow-hidden"
      style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
    >
      {site.branding.hero_url && (
        <>
          <img
            src={site.branding.hero_url}
            alt={site.branding.hero_alt ?? ""}
            className="absolute inset-0 -z-10 h-full w-full object-cover"
          />
          {/* Two layers, not one: the club chose the photograph, so the scrim
              darkens where the words sit and lets the picture be a picture
              everywhere else. */}
          <span
            aria-hidden
            className="absolute inset-0 -z-10"
            style={{
              background:
                "linear-gradient(to top, rgb(0 0 0 / 0.88) 0%, rgb(0 0 0 / 0.62) 40%, rgb(0 0 0 / 0.25) 100%)," +
                // A second wash from the left, where the words are: it keeps
                // the headline legible over a bright sky without flattening
                // the whole photograph into mud.
                "linear-gradient(to right, rgb(0 0 0 / 0.55) 0%, rgb(0 0 0 / 0.1) 60%, transparent 100%)",
            }}
          />
        </>
      )}

      <div className="mx-auto max-w-6xl px-6 pt-20 pb-2 sm:pt-28">
        <div className="flex items-center gap-3">
          <Crest site={site} size={40} inverted={!site.branding.crest_url} />
          <span className="text-xs font-semibold tracking-[0.25em] uppercase opacity-80">
            {site.short_name}
          </span>
        </div>

        <h1 className="font-display mt-6 text-[clamp(2.5rem,7vw,5rem)] leading-[0.95] font-extrabold tracking-[-0.03em] text-balance uppercase">
          {labels.title}
        </h1>
        <p className="mt-5 max-w-xl text-base/relaxed opacity-85">{labels.lead}</p>

        {/* The counting questions, answered where they are asked. */}
        <dl
          className="mt-12 grid grid-cols-3 gap-px border-t sm:mt-16"
          style={{ borderColor: "color-mix(in srgb, var(--brand-contrast) 25%, transparent)" }}
        >
          {stats.map(([label, value]) => (
            <div key={label} className="py-5 sm:py-7">
              <dd className="tabular font-display text-3xl leading-none font-extrabold sm:text-5xl">
                {value}
              </dd>
              <dt className="mt-2 text-[11px] font-semibold tracking-[0.18em] uppercase opacity-70">
                {label}
              </dt>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

/**
 * The person in charge, given a face and a name.
 *
 * A supporter asking "who is the coach" is asking about a person, so the answer
 * is a portrait and a name rather than a line in a table. Shown at the head of
 * the team's own panel because that is where the question is asked.
 */
function Manager({
  person,
  labels,
}: {
  person: TeamStaffMember;
  labels: SquadLabels;
}) {
  return (
    <div className="flex items-center gap-4">
      <span
        className="relative grid size-16 shrink-0 place-items-center overflow-hidden rounded-full text-base font-bold sm:size-20"
        style={{
          background: "color-mix(in srgb, var(--brand) 14%, transparent)",
          color: "var(--brand-text)",
          // A hairline ring in the club's colour: it separates a portrait from
          // whatever background it was shot against, which is most of what
          // makes a supplied photograph look deliberate.
          boxShadow: "0 0 0 2px color-mix(in srgb, var(--brand) 30%, transparent)",
        }}
      >
        {person.photo_url ? (
          <img
            src={person.photo_url}
            alt={person.name}
            className="h-full w-full object-cover object-top"
          />
        ) : (
          // Initials, not a silhouette: a club that has not uploaded a
          // photograph still has a named human being in the job.
          person.name
            .split(" ")
            .slice(0, 2)
            .map((part) => part[0])
            .join("")
        )}
      </span>
      <span className="min-w-0">
        <span className="block text-[11px] font-bold tracking-[0.18em] text-brand-text uppercase">
          {person.title ?? labels.staffRole(person.role)}
        </span>
        <span className="font-display mt-1 block truncate text-xl leading-tight font-bold tracking-tight sm:text-2xl">
          {person.name}
        </span>
      </span>
    </div>
  );
}

/** The first team, given the space a first team gets. */
function Feature({
  team,
  roster,
  staff,
  labels,
  eyebrow,
}: {
  team: Team;
  roster: SquadPlayer[];
  staff: TeamStaffMember[];
  labels: SquadLabels;
  eyebrow: string;
}) {
  // The coach, and only a coach. Falling back to "whoever the club listed
  // first" put the press officer in the manager's place — which is not a
  // detail, it is the wrong person on the club's shop window. A team with no
  // coach entered shows no coach.
  const manager =
    staff.find((member) => member.role === "HEAD_COACH") ??
    staff.find((member) => COACHING_ROLES.has(member.role));
  // Photographed players first, so the mosaic leads with faces rather than
  // with whoever happens to wear number 1.
  const tiles = [...faces(roster), ...roster.filter((p) => !p.photo_url)].slice(0, 20);

  return (
    <article className="grid overflow-hidden rounded-2xl border border-rule lg:grid-cols-[1fr_1.05fr]">
      <div className="flex flex-col justify-center gap-5 p-8 sm:p-12">
        <span className="text-[11px] font-bold tracking-[0.2em] text-brand-text uppercase">
          {eyebrow}
        </span>
        <h3 className="font-display text-[clamp(1.75rem,4vw,3rem)] leading-[1] font-extrabold tracking-[-0.02em]">
          {team.name}
        </h3>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-muted">
          <span className="tracking-widest uppercase">{team.code}</span>
          <span aria-hidden className="opacity-40">
            ·
          </span>
          <span>
            {roster.length > 0 ? labels.playerCount(roster.length) : labels.squadComingSoon}
          </span>
        </p>
        {manager && (
          <div className="mt-1 border-t border-rule pt-5">
            <Manager person={manager} labels={labels} />
          </div>
        )}

        <Link
          href={`/teams/${team.id}`}
          className="mt-2 inline-flex w-fit items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold transition-opacity hover:opacity-90"
          style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
        >
          {labels.viewSquad}
          <span aria-hidden>→</span>
        </Link>
      </div>

      {/* The mosaic: one tile per player, faces where the club has uploaded
          them and the shirt number where it has not.

          One design rather than two. A half-photographed squad is the normal
          state of a club's media library — the photos arrive one session at a
          time — and a layout that only works once every portrait is in would
          be broken for most of the season. The tiles are the same size either
          way, so the grid holds its rhythm as the faces fill in. */}
      <div
        className="relative overflow-hidden p-4 sm:p-6"
        style={{ background: "color-mix(in srgb, var(--brand) 7%, transparent)" }}
      >
        {tiles.length > 0 ? (
          <ul className="grid grid-cols-4 gap-1.5 sm:grid-cols-5 sm:gap-2">
            {tiles.map((player) => (
              <li
                key={player.id}
                // Portrait, not square. A club photographs its players standing
                // up, and a square crop of a standing person keeps the shirt
                // and loses the face — which is the one part anybody is
                // looking for. 3:4 is what those photographs already are.
                className="relative aspect-[3/4] overflow-hidden rounded-md"
                style={{ background: "color-mix(in srgb, var(--brand) 14%, transparent)" }}
              >
                {player.photo_url ? (
                  <img
                    src={player.photo_url}
                    alt=""
                    loading="lazy"
                    className="h-full w-full object-cover object-top"
                  />
                ) : (
                  <span
                    aria-hidden
                    className="tabular font-display absolute inset-0 grid place-items-center text-xl font-extrabold sm:text-2xl"
                    style={{ color: "color-mix(in srgb, var(--brand) 55%, transparent)" }}
                  >
                    {player.shirt_number ?? "·"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          // No squad at all yet. The age group at scale, so the panel still
          // belongs to this team rather than being an empty grey box.
          <div className="absolute inset-0 grid place-items-center opacity-[0.12]">
            <span
              className="font-display text-[12rem] leading-none font-extrabold"
              style={{ color: "var(--brand)" }}
            >
              {team.age_group ?? team.code}
            </span>
          </div>
        )}
      </div>
    </article>
  );
}

/** One academy group. */
function AgeCard({
  team,
  roster,
  labels,
}: {
  team: Team;
  roster: SquadPlayer[];
  labels: SquadLabels;
}) {
  return (
    <Link
      href={`/teams/${team.id}`}
      className="group relative flex flex-col justify-between overflow-hidden rounded-xl border border-rule p-5 transition-colors hover:border-[var(--brand)] sm:p-6"
    >
      <span
        aria-hidden
        className="absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{ background: "color-mix(in srgb, var(--brand) 6%, transparent)" }}
      />
      <span className="font-display relative text-3xl leading-none font-extrabold tracking-tight text-brand-text sm:text-4xl">
        {team.age_group ?? team.code}
      </span>
      <span className="relative mt-6 block">
        <span className="block truncate text-sm font-semibold">{team.name}</span>
        <span className="mt-0.5 flex items-center justify-between gap-2 text-xs text-ink-muted">
          {roster.length > 0 ? labels.playerCount(roster.length) : labels.squadComingSoon}
          <span
            aria-hidden
            className="translate-x-0 transition-transform group-hover:translate-x-1"
          >
            →
          </span>
        </span>
      </span>
    </Link>
  );
}

export function TeamsShowcase({
  site,
  teams,
  rosters,
  staff,
  labels,
}: {
  site: Site;
  teams: Team[];
  /** Squads by team id. Counts are facts about a team, not a detail page. */
  rosters: Record<string, SquadPlayer[]>;
  /** Touchline staff by team id — the coach is part of how a team reads. */
  staff: Record<string, TeamStaffMember[]>;
  labels: SquadLabels;
}) {
  const senior = teams.filter((team) => !team.is_academy);
  const academy = teams.filter((team) => team.is_academy);
  const registered = teams.reduce(
    (total, team) => total + (rosters[team.id]?.length ?? 0),
    0,
  );

  return (
    <>
      <Hero
        site={site}
        labels={labels}
        stats={[
          [labels.teams, String(teams.length)],
          [labels.players, String(registered)],
          [labels.academyGroups, String(academy.length)],
        ]}
      />

      <div className="mx-auto max-w-6xl space-y-14 px-6 py-14 sm:py-20">
        {senior.map((team, index) => (
          <Feature
            key={team.id}
            team={team}
            roster={rosters[team.id] ?? []}
            staff={staff[team.id] ?? []}
            labels={labels}
            // Only one side can be *the* first team; the rest are senior sides.
            eyebrow={index === 0 ? labels.firstTeam : labels.senior}
          />
        ))}

        {academy.length > 0 && (
          <section>
            <div className="mb-6 flex items-baseline justify-between gap-4 border-b border-rule pb-4">
              <h2 className="font-display text-xl font-extrabold tracking-tight sm:text-2xl">
                {labels.academy}
              </h2>
              <span className="tabular text-xs tracking-[0.2em] text-ink-muted uppercase">
                {labels.academyGroups} · {academy.length}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {academy.map((team) => (
                <AgeCard
                  key={team.id}
                  team={team}
                  roster={rosters[team.id] ?? []}
                  labels={labels}
                />
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
