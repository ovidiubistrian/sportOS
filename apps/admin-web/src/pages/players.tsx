import { usePlayers, useTeams, type PlayerSummary } from "@footbola/api-client";
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
  type Column,
} from "@footbola/ui";
import { Search, UserPlus, Users } from "lucide-react";
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

  const columns: Column<PlayerSummary>[] = [
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

  const rows = query.data?.data ?? [];
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
