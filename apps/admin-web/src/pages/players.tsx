import {
  useChangeRegistration,
  useDeletePlayer,
  usePlayers,
  useTeams,
  type PlayerSummary,
  type Team,
} from "@footbola/api-client";
import {
  Avatar,
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  NoResultsState,
  PageHeader,
  Pagination,
  Select,
  Toolbar,
  useToast,
  type Column,
} from "@footbola/ui";
import { Search, Trash2, UserPlus, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";

/**
 * Players list.
 *
 * The URL is the source of truth for filters and paging, so a filtered view is
 * shareable and survives a refresh. All filtering, sorting and paging is
 * server-side — a client-side table over 12,000 supporters is not viable, so
 * it is never built that way even while the list is small.
 */

type Tone = "success" | "warning" | "neutral" | "danger" | "info";

const STATUS_TONE: Record<string, Tone> = {
  REGISTERED: "success",
  TRIAL: "warning",
  LOANED_OUT: "info",
  INACTIVE: "neutral",
  DEPARTED: "neutral",
};

const STATUSES = ["REGISTERED", "TRIAL", "LOANED_OUT", "INACTIVE", "DEPARTED"] as const;

const PAGE_SIZE = 25;

function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function PlayersPage() {
  const navigate = useNavigate();
  const { can, path } = useSession();
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();

  const teamId = params.get("team_id") ?? undefined;
  const status = params.get("status") ?? undefined;
  const offset = Number(params.get("offset") ?? 0);
  const [search, setSearch] = useState(params.get("q") ?? "");
  const debouncedSearch = useDebounced(search);

  useEffect(() => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (debouncedSearch) next.set("q", debouncedSearch);
      else next.delete("q");
      if (next.get("q") !== current.get("q")) next.delete("offset");
      return next;
    });
  }, [debouncedSearch, setParams]);

  const { data: teams } = useTeams();
  const query = usePlayers({
    team_id: teamId,
    status,
    q: debouncedSearch || undefined,
    limit: PAGE_SIZE,
    offset,
  });

  function update(key: string, value: string | null) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== "offset") next.delete("offset");
      return next;
    });
  }

  function clearFilters() {
    setSearch("");
    setParams(new URLSearchParams());
  }

  const rows = query.data?.data ?? [];
  const canEdit = can("players.player.update");
  const canRemove = can("players.player.delete");

  // Selection lives here rather than in the table, because it is cleared by
  // things the table knows nothing about: a filter change, a page turn, a
  // successful bulk action. A checkbox still ticked next to a row that is no
  // longer on screen is how somebody deletes the wrong player.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => setSelected(new Set()), [teamId, status, debouncedSearch, offset]);

  const columns: Column<PlayerSummary>[] = [
    // Selection first, and only for people who can act on a selection. A
    // checkbox that leads to a disabled toolbar is worse than no checkbox.
    ...(canEdit
      ? [
          {
            key: "select",
            header: (
              <input
                type="checkbox"
                aria-label={t("players", "selectAll")}
                className="size-4 accent-[var(--brand)]"
                checked={rows.length > 0 && selected.size === rows.length}
                ref={(box) => {
                  if (box) box.indeterminate = selected.size > 0 && selected.size < rows.length;
                }}
                onChange={(event) =>
                  setSelected(
                    event.target.checked ? new Set(rows.map((row) => row.id)) : new Set(),
                  )
                }
              />
            ),
            width: "2.5rem",
            render: (player: PlayerSummary) => (
              <input
                type="checkbox"
                aria-label={player.display_name}
                className="size-4 accent-[var(--brand)]"
                checked={selected.has(player.id)}
                // The row itself opens the player, so the box must not.
                onClick={(event) => event.stopPropagation()}
                onChange={(event) => {
                  const next = new Set(selected);
                  if (event.target.checked) next.add(player.id);
                  else next.delete(player.id);
                  setSelected(next);
                }}
              />
            ),
          } as Column<PlayerSummary>,
        ]
      : []),
    {
      key: "shirt",
      header: "#",
      width: "3.5rem",
      align: "right",
      render: (player) => (
        <span className="font-medium text-text-tertiary" data-numeric>
          {player.shirt_number ?? "—"}
        </span>
      ),
    },
    {
      key: "name",
      header: t("players", "columnPlayer"),
      render: (player) => (
        <span className="flex items-center gap-2.5">
          <Avatar name={player.display_name} size="sm" />
          <span className="font-medium text-text">{player.display_name}</span>
        </span>
      ),
    },
    {
      key: "team",
      header: t("players", "columnTeam"),
      render: (player) =>
        player.team ? (
          <Badge tone="outline">{player.team.name}</Badge>
        ) : (
          <span className="text-text-tertiary">—</span>
        ),
    },
    {
      key: "position",
      header: t("players", "columnPosition"),
      hideBelow: "md",
      render: (player) => (
        <span className="text-text-secondary">{player.primary_position ?? "—"}</span>
      ),
    },
    {
      key: "status",
      header: t("players", "columnStatus"),
      align: "right",
      render: (player) => (
        <Badge tone={STATUS_TONE[player.status] ?? "neutral"} dot>
          {player.status.replace("_", " ").toLowerCase()}
        </Badge>
      ),
    },
  ];

  const meta = query.data?.page;
  const hasFilters = Boolean(teamId || status || debouncedSearch);

  if (query.isError) {
    return (
      <ErrorState
        error={query.error}
        onRetry={() => void query.refetch()}
        title={t("common", "somethingWentWrong")}
        retryLabel={t("common", "tryAgain")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <>
            <Users className="size-3.5" />
            {t("players", "eyebrow")}
          </>
        }
        title={t("players", "title")}
        count={meta?.total}
        description={t("players", "description")}
        action={
          can("players.player.create") ? (
            <Button variant="primary" onClick={() => navigate(path("/players/new"))}>
              <UserPlus />
              {t("players", "register")}
            </Button>
          ) : undefined
        }
      />

      <Toolbar>
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("players", "searchPlaceholder")}
          aria-label={t("players", "searchLabel")}
          leading={<Search />}
          className="w-64"
        />
        <div className="w-44">
          <Select
            ariaLabel={t("players", "filterTeam")}
            value={teamId ?? ""}
            placeholder={t("players", "allTeams")}
            onChange={(value) => update("team_id", value || null)}
            options={[
              { value: "", label: t("players", "allTeams") },
              ...(teams ?? []).map((team) => ({ value: team.id, label: team.name })),
            ]}
          />
        </div>
        <div className="w-40">
          <Select
            ariaLabel={t("players", "filterStatus")}
            value={status ?? ""}
            placeholder={t("players", "allStatuses")}
            onChange={(value) => update("status", value || null)}
            options={[
              { value: "", label: t("players", "allStatuses") },
              ...STATUSES.map((value) => ({
                value,
                label: value.replace("_", " ").toLowerCase(),
              })),
            ]}
          />
        </div>
        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            {t("common", "clear")}
          </Button>
        )}
      </Toolbar>

      {!query.isLoading && rows.length === 0 ? (
        hasFilters ? (
          <NoResultsState
            onClear={clearFilters}
            title={t("common", "noResultsTitle")}
            description={t("common", "noResultsBody")}
            clearLabel={t("common", "clearFilters")}
          />
        ) : (
          <EmptyState
            icon={<Users />}
            title={t("players", "emptyTitle")}
            description={t("players", "emptyBody")}
            action={
              can("players.player.create") ? (
                <Button variant="primary" onClick={() => navigate(path("/players/new"))}>
                  <UserPlus />
                  {t("players", "register")}
                </Button>
              ) : null
            }
          />
        )
      ) : (
        <>
          {selected.size > 0 && (
            <SelectionBar
              ids={[...selected]}
              teams={teams ?? []}
              canRemove={canRemove}
              onDone={() => setSelected(new Set())}
            />
          )}
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(player) => player.id}
            isLoading={query.isLoading}
            onRowClick={(player) => navigate(path(`/players/${player.id}`))}
          />
          {meta && (
            <Pagination
              offset={offset}
              limit={PAGE_SIZE}
              total={meta.total}
              isEstimate={meta.total_is_estimate}
              hasMore={meta.has_more}
              ofLabel={t("common", "of")}
              previousLabel={t("common", "previousPage")}
              nextLabel={t("common", "nextPage")}
              onChange={(next) => update("offset", next === 0 ? null : String(next))}
            />
          )}
        </>
      )}
    </div>
  );
}


/**
 * What to do with the players somebody has ticked.
 *
 * Moving and removing, because those are the two things a club does to a group
 * rather than to a person: a whole age group moves up in July, and an import
 * that brought in the wrong squad has to go.
 *
 * One request per player rather than a bulk endpoint. Fifty players is fifty
 * requests and takes a moment, which is honest — each one is a real
 * registration change with its own audit entry, and a bulk endpoint would
 * either lose that or lie about it. The count reported afterwards is what
 * actually succeeded, not what was asked for.
 */
function SelectionBar({
  ids,
  teams,
  canRemove,
  onDone,
}: {
  ids: string[];
  teams: Team[];
  canRemove: boolean;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const move = useChangeRegistration();
  const remove = useDeletePlayer();
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function run(what: (id: string) => Promise<unknown>, done: (n: number) => string) {
    setBusy(true);
    let ok = 0;
    for (const id of ids) {
      try {
        await what(id);
        ok += 1;
      } catch {
        // Keep going: one player with a shirt number clash should not stop the
        // other forty-nine, and the count below says how many made it.
      }
    }
    setBusy(false);
    setConfirming(false);
    onDone();
    if (ok === ids.length) toast.success(done(ok));
    else toast.error(`${done(ok)} — ${ids.length - ok} failed.`);
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-brand-border bg-brand-bg px-4 py-3">
      <span className="text-sm font-medium text-text">
        {t("players", "selectedCount", { count: String(ids.length) })}
      </span>

      <span className="ml-auto flex flex-wrap items-center gap-2">
        <Select
          value={target}
          ariaLabel={t("players", "moveTo")}
          placeholder={t("players", "moveTo")}
          size="sm"
          options={teams.map((team) => ({ value: team.id, label: team.name }))}
          onChange={(value) => {
            setTarget(value);
            if (value) {
              void run(
                (id) => move.mutateAsync({ id, change: { team_id: value } }),
                (n) => t("players", "moved", { count: String(n) }),
              );
              setTarget("");
            }
          }}
        />

        {canRemove &&
          (confirming ? (
            <>
              <span className="text-sm text-text-secondary">{t("players", "removeSure")}</span>
              <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                {t("common", "cancel")}
              </Button>
              <Button
                variant="danger"
                size="sm"
                loading={busy}
                onClick={() =>
                  void run(
                    (id) => remove.mutateAsync(id),
                    (n) => t("players", "removed", { count: String(n) }),
                  )
                }
              >
                {t("players", "removeConfirm")}
              </Button>
            </>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
              <Trash2 />
              {t("players", "remove")}
            </Button>
          ))}
      </span>
    </div>
  );
}
