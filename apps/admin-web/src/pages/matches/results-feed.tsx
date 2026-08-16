import {
  useFeed,
  useProviderLeagueTeams,
  useProviderLeagues,
  useSyncFeed,
  useUpdateFeed,
} from "@footbola/api-client";
import { Badge, Button, Card, Field, Select, Spinner, useToast } from "@footbola/ui";
import { RefreshCw, Unlink } from "lucide-react";
import { useState } from "react";

/**
 * Where a club's results come from.
 *
 * Two dropdowns and nothing else: the division, then everyone in it, and the
 * club points at itself. Choosing from a list rather than typing a name is
 * what removes the only decision that could put another club's fixtures on
 * this one's website.
 *
 * Most clubs never see this — entering a league links the feed on its own when
 * the name and country agree without ambiguity. It exists for the rest: a club
 * whose name the provider spells differently, one of two with the same name,
 * and anyone who linked the wrong thing and wants it undone.
 *
 * A division the provider does not carry is not an error. Liga 4 and below are
 * not covered anywhere, and a club that reads "your division is not covered,
 * add your fixtures here" has learned something true.
 */
export function ResultsFeed({ clubId, country }: { clubId: string; country: string }) {
  const toast = useToast();
  const feed = useFeed(clubId);
  const update = useUpdateFeed(clubId);
  const sync = useSyncFeed(clubId);

  const linked = Boolean(feed.data?.provider_team_id);
  const [picking, setPicking] = useState(false);

  // The catalogue costs a call against an allowance shared by every club, so
  // it is not fetched until somebody actually opens the picker.
  const catalogue = useProviderLeagues(country, picking || (!linked && feed.isSuccess));

  const [leagueId, setLeagueId] = useState("");
  const league = catalogue.data?.leagues.find((row) => row.id === leagueId);
  const teams = useProviderLeagueTeams(leagueId, league?.season ?? null);
  const [teamId, setTeamId] = useState("");

  if (feed.isLoading) return null;
  if (feed.data && !feed.data.provider_available) return null;

  function connect() {
    const team = teams.data?.find((row) => row.id === teamId);
    if (!team || !league?.season) return;
    update.mutate(
      {
        mode: "AUTO",
        provider_team_id: team.id,
        provider_team_name: team.name,
        season_year: league.season,
      },
      {
        onSuccess: () => {
          toast.success(`Connected to ${team.name}. Fixtures arrive shortly.`);
          setPicking(false);
          sync.mutate();
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  function disconnect() {
    update.mutate(
      { mode: "MANUAL", provider_team_id: null, provider_team_name: null },
      {
        onSuccess: () => toast.success("Disconnected. Your fixtures are yours to edit."),
        onError: (error) => toast.error(error.message),
      },
    );
  }

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-text">Results feed</h2>
          <p className="mt-1 text-sm text-text-secondary">
            {linked
              ? "Fixtures, results and the table arrive on their own."
              : "Connect your club and stop typing fixtures in by hand."}
          </p>
        </div>
        {linked && (
          <div className="flex items-center gap-2">
            <Badge tone="success">{feed.data?.provider_team_name}</Badge>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => sync.mutate()}
              loading={sync.isPending}
            >
              <RefreshCw />
              Fetch now
            </Button>
            <Button variant="ghost" size="sm" onClick={disconnect} loading={update.isPending}>
              <Unlink />
              Disconnect
            </Button>
          </div>
        )}
      </div>

      {feed.data?.last_error && (
        <p className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger">
          {feed.data.last_error}
        </p>
      )}

      {linked && feed.data && !feed.data.last_fixtures_at && (
        <p className="text-sm text-text-secondary">
          Connected. The first fetch runs shortly — or press Fetch now.
        </p>
      )}

      {!linked && (
        <>
          {catalogue.isLoading && <Spinner />}

          {/* Not an error state. Most Romanian clubs play below the third
              tier, which no provider carries, and saying so plainly is more
              use than a control that does nothing. */}
          {catalogue.data && !catalogue.data.available && (
            <p className="text-sm text-text-secondary">{catalogue.data.reason}</p>
          )}

          {catalogue.data?.available && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Division" htmlFor="feed-league">
                {(props) => (
                  <Select
                    {...props}
                    value={leagueId}
                    placeholder="Choose your division…"
                    options={catalogue.data.leagues.map((row) => ({
                      value: row.id,
                      label: row.name,
                      description: row.season ? `Season ${row.season}` : undefined,
                    }))}
                    onChange={(value) => {
                      setLeagueId(value);
                      setTeamId("");
                    }}
                  />
                )}
              </Field>

              <Field
                label="Your club"
                htmlFor="feed-team"
                help={
                  leagueId && teams.isSuccess && teams.data.length === 0
                    ? "The provider lists nobody in that division this season."
                    : undefined
                }
              >
                {(props) => (
                  <Select
                    {...props}
                    value={teamId}
                    disabled={!leagueId || teams.isLoading}
                    placeholder={teams.isLoading ? "Loading…" : "Choose your club…"}
                    options={(teams.data ?? []).map((team) => ({
                      value: team.id,
                      label: team.name,
                      description: team.founded ? `Founded ${team.founded}` : undefined,
                    }))}
                    onChange={setTeamId}
                  />
                )}
              </Field>
            </div>
          )}

          {catalogue.data?.available && (
            <Button onClick={connect} disabled={!teamId} loading={update.isPending}>
              Connect
            </Button>
          )}
        </>
      )}
    </Card>
  );
}
