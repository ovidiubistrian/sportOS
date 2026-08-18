import {
  useCompetitionEntries,
  useCompetitions,
  useCreateMatch,
  useJoinCompetition,
  useMatches,
  useTable,
  useUpdateMatch,
  type CompetitionEntry,
  type DirectoryClub,
  type Match,
  type MatchStatus,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Section,
  Segmented,
  Select,
  Skeleton,
  Switch,
  cn,
  useToast,
} from "@footbola/ui";
import { CalendarDays, Plus, Trophy } from "lucide-react";
import { useMemo, useState } from "react";

import { useI18n } from "../../app/locale";
import { ResultsFeed } from "./results-feed";
import { useSession } from "../../app/session";
import { MatchdayConsole } from "./matchday-console";
import { OpponentPicker } from "./opponent-picker";

/**
 * Competitions, fixtures and results — the club's side of matchday.
 *
 * One page rather than three, because the three are one job: you enter a
 * competition so you can add its fixtures, and you add a fixture so you can
 * record its result. Splitting them across routes would mean walking the
 * navigation three times to do one week's admin.
 *
 * The table is read-only here on purpose. It is computed from the results
 * above it, and the moment it becomes editable the two disagree.
 */

const STATUSES: MatchStatus[] = [
  "SCHEDULED",
  "POSTPONED",
  "CANCELLED",
  "FINISHED",
  "AWARDED",
];

function statusTone(status: MatchStatus) {
  if (status === "FINISHED" || status === "AWARDED") return "success" as const;
  if (status === "CANCELLED") return "danger" as const;
  if (status === "POSTPONED") return "warning" as const;
  return "neutral" as const;
}

/** `datetime-local` wants a naive local string; the API speaks ISO with a zone. */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

/* --- entering a competition ------------------------------------------------ */

function JoinDialog({
  open,
  onOpenChange,
  clubId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clubId: string;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const catalogue = useCompetitions();
  const join = useJoinCompetition();

  const year = new Date().getFullYear();
  const [competitionId, setCompetitionId] = useState("");
  const [season, setSeason] = useState(`${year}/${String(year + 1).slice(2)}`);
  const [start, setStart] = useState(`${year}-07-01`);
  const [end, setEnd] = useState(`${year + 1}-06-30`);

  const options = (catalogue.data ?? []).map((competition) => ({
    value: competition.id,
    label: competition.name,
    description: competition.tier ? `Tier ${competition.tier}` : competition.scope,
  }));

  function submit() {
    const competition = catalogue.data?.find((row) => row.id === competitionId);
    join.mutate(
      {
        club_id: clubId,
        competition_id: competitionId,
        season_name: season,
        start_date: start,
        end_date: end,
      },
      {
        onSuccess: () => {
          toast.success(t("matches", "joined", { competition: competition?.name ?? "" }));
          onOpenChange(false);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("matches", "joinTitle")}
      description={t("matches", "joinBody")}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button onClick={submit} loading={join.isPending} disabled={!competitionId || !season}>
            {t("matches", "join")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("matches", "competition")} required>
          {(props) => (
            <Select
              {...props}
              value={competitionId}
              onChange={setCompetitionId}
              options={options}
              disabled={catalogue.isLoading}
            />
          )}
        </Field>

        <Field label={t("matches", "season")} required>
          {(props) => (
            <Input
              {...props}
              value={season}
              onChange={(event) => setSeason(event.target.value)}
              placeholder={t("matches", "seasonPlaceholder")}
            />
          )}
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("matches", "startDate")}>
            {(props) => (
              <Input
                {...props}
                type="date"
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            )}
          </Field>
          <Field label={t("matches", "endDate")}>
            {(props) => (
              <Input
                {...props}
                type="date"
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            )}
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

/* --- adding a fixture ------------------------------------------------------ */

function FixtureDialog({
  open,
  onOpenChange,
  clubId,
  entries,
  defaultSeasonId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clubId: string;
  entries: CompetitionEntry[];
  defaultSeasonId: string | null;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const create = useCreateMatch();

  const [seasonId, setSeasonId] = useState(defaultSeasonId ?? "");
  const [opponent, setOpponent] = useState<DirectoryClub | null>(null);
  const [atHome, setAtHome] = useState<"HOME" | "AWAY">("HOME");
  const [kickoff, setKickoff] = useState("");
  const [confirmed, setConfirmed] = useState(true);
  const [roundNumber, setRoundNumber] = useState("");
  const [venue, setVenue] = useState("");
  const [ticketUrl, setTicketUrl] = useState("");

  const entry = entries.find((row) => row.id === seasonId);
  const isLeague = entry?.competition_format === "LEAGUE";

  function submit() {
    if (!opponent || !seasonId) return;
    create.mutate(
      {
        club_id: clubId,
        competition_season_id: seasonId,
        opponent_club_id: opponent.id,
        at_home: atHome === "HOME",
        round_kind: isLeague ? "MATCHDAY" : "ROUND",
        round_number: roundNumber ? Number(roundNumber) : null,
        kickoff_at: fromLocalInput(kickoff),
        kickoff_is_confirmed: confirmed,
        venue_name: venue || null,
        ticket_url: ticketUrl || null,
      },
      {
        onSuccess: () => {
          toast.success(t("matches", "fixtureAdded"));
          setOpponent(null);
          setKickoff("");
          setRoundNumber("");
          setTicketUrl("");
          onOpenChange(false);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("matches", "addFixtureTitle")}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            onClick={submit}
            loading={create.isPending}
            disabled={!opponent || !seasonId}
          >
            {t("matches", "addFixture")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label={t("matches", "competition")} required className="sm:col-span-2">
          {(props) => (
            <Select
              {...props}
              value={seasonId}
              onChange={setSeasonId}
              options={entries.map((row) => ({
                value: row.id,
                label: `${row.competition_name} · ${row.season_name}`,
              }))}
            />
          )}
        </Field>

        <div className="sm:col-span-2">
          <p className="mb-1.5 text-xs font-medium text-text">{t("matches", "opponent")}</p>
          <OpponentPicker seasonId={seasonId || null} value={opponent} onChange={setOpponent} />
        </div>

        <Field label={t("matches", "homeAway")}>
          {() => (
            <Segmented
              value={atHome}
              onChange={setAtHome}
              ariaLabel={t("matches", "homeAway")}
              options={[
                { value: "HOME", label: t("matches", "home") },
                { value: "AWAY", label: t("matches", "away") },
              ]}
            />
          )}
        </Field>

        <Field label={isLeague ? t("matches", "roundNumber") : t("matches", "round")}>
          {(props) => (
            <Input
              {...props}
              type="number"
              min={1}
              value={roundNumber}
              onChange={(event) => setRoundNumber(event.target.value)}
            />
          )}
        </Field>

        <Field label={t("matches", "kickoff")}>
          {(props) => (
            <Input
              {...props}
              type="datetime-local"
              value={kickoff}
              onChange={(event) => setKickoff(event.target.value)}
            />
          )}
        </Field>

        <Field label={t("matches", "venue")}>
          {(props) => (
            <Input
              {...props}
              value={venue}
              onChange={(event) => setVenue(event.target.value)}
              disabled={atHome === "AWAY" && !venue}
            />
          )}
        </Field>

        <Field
          label={t("matches", "ticketUrl")}
          help={t("matches", "ticketUrlHint")}
          className="sm:col-span-2"
        >
          {(props) => (
            <Input
              {...props}
              type="url"
              value={ticketUrl}
              onChange={(event) => setTicketUrl(event.target.value)}
              placeholder="https://"
            />
          )}
        </Field>

        <label className="flex items-center gap-2.5 text-sm text-text sm:col-span-2">
          <Switch
            checked={!confirmed}
            onChange={(value) => setConfirmed(!value)}
            label={t("matches", "kickoffTbc")}
          />
          {t("matches", "kickoffTbc")}
        </label>
      </div>
    </Dialog>
  );
}

/* --- editing a fixture ----------------------------------------------------- */

/**
 * One dialog for the whole life of a fixture.
 *
 * Rescheduling and recording a result are the same act from the club's side —
 * you open the match and change what is now true about it — and a club that
 * has to find a different screen to move a kick-off will simply not move it.
 */
function FixtureEditor({
  match,
  onClose,
  clubId,
}: {
  match: Match | null;
  onClose: () => void;
  clubId: string;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const update = useUpdateMatch(clubId);

  const [home, setHome] = useState("");
  const [away, setAway] = useState("");
  const [status, setStatus] = useState<MatchStatus>("SCHEDULED");
  const [kickoff, setKickoff] = useState("");
  const [confirmed, setConfirmed] = useState(true);
  const [venue, setVenue] = useState("");
  const [ticketUrl, setTicketUrl] = useState("");
  const [seeded, setSeeded] = useState<string | null>(null);

  // Seed from the match the first time this one is opened, without an effect:
  // the dialog is keyed by match id and rendering is the only trigger needed.
  if (match && seeded !== match.id) {
    setSeeded(match.id);
    setHome(match.home_score?.toString() ?? "");
    setAway(match.away_score?.toString() ?? "");
    setStatus(match.status);
    setKickoff(toLocalInput(match.kickoff_at));
    setConfirmed(match.kickoff_is_confirmed);
    setVenue(match.venue_name ?? "");
    setTicketUrl(match.ticket_url ?? "");
  }

  const played = status === "FINISHED" || status === "AWARDED";

  function submit() {
    if (!match) return;
    update.mutate(
      {
        id: match.id,
        changes: {
          status,
          kickoff_at: fromLocalInput(kickoff),
          kickoff_is_confirmed: confirmed,
          venue_name: venue || null,
          ticket_url: ticketUrl || null,
          // A postponement has no score, and sending one would be rejected by
          // the check constraint that keeps the two in step.
          home_score: played ? Number(home) : null,
          away_score: played ? Number(away) : null,
        },
      },
      {
        onSuccess: () => {
          toast.success(played ? t("matches", "resultSaved") : t("matches", "saved"));
          onClose();
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  return (
    <Dialog
      open={Boolean(match)}
      onOpenChange={(open) => !open && onClose()}
      title={t("matches", "editFixture")}
      description={t("matches", "recordResultBody")}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common", "cancel")}
          </Button>
          <Button
            onClick={submit}
            loading={update.isPending}
            disabled={played && (home === "" || away === "")}
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      {match && (
        <div className="space-y-5">
          <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
            <p className="truncate text-right text-sm font-medium text-text">
              {match.home.name}
            </p>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={0}
                max={99}
                value={home}
                onChange={(event) => setHome(event.target.value)}
                aria-label={t("matches", "scoreHome")}
                disabled={!played}
                className="w-14 text-center tabular-nums"
              />
              <span className="text-text-tertiary">–</span>
              <Input
                type="number"
                min={0}
                max={99}
                value={away}
                onChange={(event) => setAway(event.target.value)}
                aria-label={t("matches", "scoreAway")}
                disabled={!played}
                className="w-14 text-center tabular-nums"
              />
            </div>
            <p className="truncate text-sm font-medium text-text">{match.away.name}</p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("matches", "status")}>
              {(props) => (
                <Select
                  {...props}
                  value={status}
                  onChange={setStatus}
                  options={STATUSES.map((value) => ({
                    value,
                    label: t("matches", `status${value}` as "statusSCHEDULED"),
                  }))}
                />
              )}
            </Field>

            <Field label={t("matches", "kickoff")}>
              {(props) => (
                <Input
                  {...props}
                  type="datetime-local"
                  value={kickoff}
                  onChange={(event) => setKickoff(event.target.value)}
                />
              )}
            </Field>

            <Field label={t("matches", "venue")}>
              {(props) => (
                <Input
                  {...props}
                  value={venue}
                  onChange={(event) => setVenue(event.target.value)}
                />
              )}
            </Field>

            <Field label={t("matches", "ticketUrl")} help={t("matches", "ticketUrlHint")}>
              {(props) => (
                <Input
                  {...props}
                  type="url"
                  value={ticketUrl}
                  onChange={(event) => setTicketUrl(event.target.value)}
                  placeholder="https://"
                />
              )}
            </Field>
          </div>

          <label className="flex items-center gap-2.5 text-sm text-text">
            <Switch
              checked={!confirmed}
              onChange={(value) => setConfirmed(!value)}
              label={t("matches", "kickoffTbc")}
            />
            {t("matches", "kickoffTbc")}
          </label>
        </div>
      )}
    </Dialog>
  );
}

/* --- fixtures list --------------------------------------------------------- */

function FixtureRow({
  match,
  onResult,
  canManage,
}: {
  match: Match;
  onResult: () => void;
  canManage: boolean;
}) {
  const { t, formatDate } = useI18n();
  const played = match.home_score !== null && match.away_score !== null;

  return (
    <li className="grid items-center gap-3 border-b border-border py-3 last:border-0 sm:grid-cols-[10rem_1fr_auto]">
      <div className="text-xs">
        <p className="font-medium text-text tabular-nums">
          {match.kickoff_at
            ? formatDate(match.kickoff_at, {
                day: "numeric",
                month: "short",
                ...(match.kickoff_is_confirmed
                  ? { hour: "2-digit", minute: "2-digit" }
                  : {}),
              })
            : "—"}
        </p>
        <p className="mt-0.5 text-text-tertiary">
          {[
            match.competition_name,
            match.round_number ? `${t("matches", "round")} ${match.round_number}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className={cn("font-medium", !match.is_home && "text-text-secondary")}>
          {match.home.name}
        </span>
        {played ? (
          <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-xs font-bold tabular-nums">
            {match.home_score}–{match.away_score}
          </span>
        ) : (
          <span className="text-text-tertiary">–</span>
        )}
        <span className={cn("font-medium", match.is_home && "text-text-secondary")}>
          {match.away.name}
        </span>
      </div>

      <div className="flex items-center gap-2 sm:justify-end">
        {match.venue_name && (
          <span className="hidden text-xs text-text-tertiary lg:inline">
            {match.venue_name}
          </span>
        )}
        <Badge tone={statusTone(match.status)}>
          {t("matches", `status${match.status}` as "statusSCHEDULED")}
        </Badge>
        {canManage && (
          <Button variant="ghost" size="sm" onClick={onResult}>
            {played ? t("matches", "edit") : t("matches", "recordResult")}
          </Button>
        )}
      </div>
    </li>
  );
}

/* --- the page -------------------------------------------------------------- */

export function MatchesPage() {
  const { me, club, can } = useSession();
  const { t, formatNumber } = useI18n();
  const canManage = can("teams.team.manage");

  const entries = useCompetitionEntries(club.id);
  const matches = useMatches(club.id);

  const [joining, setJoining] = useState(false);
  const [addingFixture, setAddingFixture] = useState(false);
  const [result, setResult] = useState<Match | null>(null);
  const [tableSeason, setTableSeason] = useState("");

  const leagues = useMemo(
    () => (entries.data ?? []).filter((row) => row.competition_format === "LEAGUE"),
    [entries.data],
  );
  const activeSeason = tableSeason || leagues[0]?.id || "";
  const table = useTable(activeSeason || null);

  if (entries.isError) {
    return (
      <ErrorState
        error={entries.error}
        onRetry={() => void entries.refetch()}
        title={t("common", "somethingWentWrong")}
        retryLabel={t("common", "tryAgain")}
      />
    );
  }

  const rows = matches.data ?? [];
  const scheduled = rows.filter((match) => match.status === "SCHEDULED");
  const done = rows.filter((match) => match.status !== "SCHEDULED");

  // The console appears for the match that is actually on, and for the one
  // about to be — which is when somebody is standing at the ground with a
  // phone. The rest of the season it is not there, because the rest of the
  // season nobody needs it.
  const soon = Date.now() + 3 * 60 * 60 * 1000;
  const onNow =
    rows.find((match) => match.status === "LIVE") ??
    rows.find(
      (match) =>
        match.status === "SCHEDULED" &&
        match.kickoff_at != null &&
        new Date(match.kickoff_at).getTime() < soon,
    );

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={
          <>
            <CalendarDays className="size-3.5" />
            {t("matches", "eyebrow")}
          </>
        }
        title={t("matches", "title")}
        description={t("matches", "description")}
        action={
          canManage && (
            <>
              <Button variant="secondary" onClick={() => setJoining(true)}>
                <Trophy className="size-4" />
                {t("matches", "join")}
              </Button>
              <Button
                onClick={() => setAddingFixture(true)}
                disabled={(entries.data ?? []).length === 0}
              >
                <Plus className="size-4" />
                {t("matches", "addFixture")}
              </Button>
            </>
          )
        }
      />

      {canManage && onNow && <MatchdayConsole match={onNow} clubId={club.id} />}

      {entries.isLoading ? (
        <Skeleton className="h-24" />
      ) : (entries.data ?? []).length === 0 ? (
        <EmptyState
          icon={<Trophy />}
          title={t("matches", "noCompetitions")}
          description={t("matches", "noCompetitionsBody")}
          action={
            canManage && (
              <Button onClick={() => setJoining(true)}>{t("matches", "join")}</Button>
            )
          }
        />
      ) : (
        <>
          {/* Where results come from, above the fixtures they fill in. A club
              that has just entered a league is one step from never typing a
              fixture again, and that step should be the next thing it sees. */}
          {canManage && <ResultsFeed clubId={club.id} country={me.active_tenant?.country_code ?? "RO"} />}

          <Section
            title={t("matches", "competitions")}
            description={t("matches", "competitionsHint")}
          >
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(entries.data ?? []).map((entry) => (
                <Card key={entry.id} className="p-4">
                  <p className="text-sm font-medium text-text">{entry.competition_name}</p>
                  <p className="mt-0.5 text-xs text-text-secondary">{entry.season_name}</p>
                  <p className="mt-3 text-xs text-text-tertiary tabular-nums">
                    {formatNumber(
                      rows.filter((match) => match.competition_season_id === entry.id).length,
                    )}{" "}
                    {t("matches", "fixtures").toLowerCase()}
                  </p>
                </Card>
              ))}
            </div>
          </Section>

          <Section title={t("matches", "fixtures")} description={t("matches", "fixturesHint")}>
            {matches.isLoading ? (
              <Skeleton className="h-40" />
            ) : rows.length === 0 ? (
              <EmptyState
                icon={<CalendarDays />}
                title={t("matches", "noFixtures")}
                description={t("matches", "noFixturesBody")}
              />
            ) : (
              <Card className="px-4">
                <ul>
                  {[...scheduled, ...done].map((match) => (
                    <FixtureRow
                      key={match.id}
                      match={match}
                      canManage={canManage}
                      onResult={() => setResult(match)}
                    />
                  ))}
                </ul>
              </Card>
            )}
          </Section>

          {leagues.length > 0 && (
            <Section
              title={t("matches", "table")}
              description={t("matches", "tableHint")}
              action={
                leagues.length > 1 && (
                  <Select
                    value={activeSeason}
                    onChange={setTableSeason}
                    size="sm"
                    className="w-56"
                    options={leagues.map((row) => ({
                      value: row.id,
                      label: `${row.competition_name} · ${row.season_name}`,
                    }))}
                  />
                )
              }
            >
              <Card className="overflow-x-auto">
                <table className="w-full min-w-[36rem] border-collapse text-sm tabular-nums">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-text-secondary">
                      <th className="px-4 py-2.5 font-medium">{t("matches", "position")}</th>
                      <th className="py-2.5 font-medium">{t("matches", "club")}</th>
                      {(["played", "won", "drawn", "lost", "goalDifference", "points"] as const).map(
                        (key) => (
                          <th key={key} className="px-2 py-2.5 text-center font-medium">
                            {t("matches", key)}
                          </th>
                        ),
                      )}
                      <th className="px-4 py-2.5 font-medium">{t("matches", "form")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(table.data ?? []).map((row) => (
                      <tr
                        key={row.club.id}
                        className={cn(
                          "border-b border-border last:border-0",
                          row.club.id === club.directory_club_id && "bg-brand-subtle",
                        )}
                      >
                        <td className="px-4 py-2.5 text-text-tertiary">{row.position}</td>
                        <td className="py-2.5 font-medium">{row.club.name}</td>
                        <td className="px-2 py-2.5 text-center text-text-secondary">
                          {row.played}
                        </td>
                        <td className="px-2 py-2.5 text-center text-text-secondary">{row.won}</td>
                        <td className="px-2 py-2.5 text-center text-text-secondary">
                          {row.drawn}
                        </td>
                        <td className="px-2 py-2.5 text-center text-text-secondary">{row.lost}</td>
                        <td className="px-2 py-2.5 text-center text-text-secondary">
                          {row.goal_difference > 0
                            ? `+${row.goal_difference}`
                            : row.goal_difference}
                        </td>
                        <td className="px-2 py-2.5 text-center font-semibold">{row.points}</td>
                        <td className="px-4 py-2.5">
                          <span className="flex gap-1">
                            {row.form.map((letter, index) => (
                              <span
                                key={index}
                                className={cn(
                                  "grid size-4 place-items-center rounded-[3px] text-[9px] font-bold text-white",
                                  letter === "W" && "bg-success",
                                  letter === "D" && "bg-warning",
                                  letter === "L" && "bg-danger",
                                )}
                              >
                                {letter}
                              </span>
                            ))}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(table.data ?? []).length === 0 && !table.isLoading && (
                  <p className="px-4 py-6 text-center text-sm text-text-secondary">
                    {t("matches", "tableEmpty")}
                  </p>
                )}
              </Card>
            </Section>
          )}
        </>
      )}

      <JoinDialog open={joining} onOpenChange={setJoining} clubId={club.id} />
      <FixtureDialog
        open={addingFixture}
        onOpenChange={setAddingFixture}
        clubId={club.id}
        entries={entries.data ?? []}
        defaultSeasonId={leagues[0]?.id ?? entries.data?.[0]?.id ?? null}
      />
      <FixtureEditor match={result} onClose={() => setResult(null)} clubId={club.id} />
    </div>
  );
}
