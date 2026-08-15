import { usePlayers, useTeams, type Team } from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  Section,
  cn,
} from "@footbola/ui";
import { ArrowUpRight, Pencil, Plus, Shirt } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";
import { TeamEditor } from "./team-editor";

/**
 * Teams.
 *
 * Cards rather than a table: a club has ten to twenty teams, not ten thousand,
 * and at that size the useful question is "which squad do I want" — which a
 * grid answers faster than five columns of attributes.
 */

function TeamCard({ team, onEdit }: { team: Team; onEdit?: () => void }) {
  const { path } = useSession();
  const { t, plural, formatNumber } = useI18n();
  // One request per card is fine at this cardinality and gives each squad its
  // real size, which is the number a coach is actually looking for.
  const players = usePlayers({ team_id: team.id, limit: 1, with_total: true });

  return (
    <Link to={path(`/players?team_id=${team.id}`)} className="group">
      <Card interactive className="h-full p-4">
        <div className="flex items-start justify-between gap-3">
          <span
            aria-hidden
            className={cn(
              "grid size-10 shrink-0 place-items-center rounded-lg text-xs font-bold",
              team.is_academy
                ? "bg-info-bg text-info"
                : "bg-brand-subtle text-brand-text",
            )}
          >
            {team.code}
          </span>
          <span className="flex items-center gap-1">
            {onEdit && (
              // Inside a Link, so the click has to be stopped from navigating.
              <button
                type="button"
                aria-label={t("squads", "edit")}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onEdit();
                }}
                className="rounded p-1 text-text-tertiary opacity-0 transition-opacity hover:bg-bg-muted hover:text-text group-hover:opacity-100"
              >
                <Pencil className="size-3.5" />
              </button>
            )}
            <ArrowUpRight className="size-4 text-text-tertiary opacity-0 transition-opacity group-hover:opacity-100" />
          </span>
        </div>

        <p className="mt-3 truncate text-sm font-medium text-text">{team.name}</p>
        <p className="mt-0.5 text-xs text-text-secondary">
          {[team.age_group ?? "Senior", team.gender.toLowerCase()].join(" · ")}
        </p>

        <div className="mt-4 flex items-end justify-between gap-2">
          {players.isLoading ? (
            <Skeleton className="h-7 w-12" />
          ) : (
            <p className="display text-2xl font-semibold text-text">
              {formatNumber(players.data?.page.total ?? 0)}
              <span className="ml-1 text-xs font-normal text-text-tertiary">
                {plural("teams", "playerCount", players.data?.page.total ?? 0)}
              </span>
            </p>
          )}
          <Badge tone={team.is_academy ? "info" : "neutral"}>
            {team.is_academy ? t("teams", "academy") : t("teams", "senior")}
          </Badge>
        </div>
      </Card>
    </Link>
  );
}

export function TeamsPage() {
  const query = useTeams();
  const { t } = useI18n();
  const { can } = useSession();
  const canManage = can("teams.team.manage");

  // `undefined` means closed; `null` means open on a new team.
  const [editing, setEditing] = useState<Team | null | undefined>(undefined);

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

  const teams = query.data ?? [];
  const academy = teams.filter((team) => team.is_academy);
  const senior = teams.filter((team) => !team.is_academy);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={
          <>
            <Shirt className="size-3.5" />
            {t("teams", "eyebrow")}
          </>
        }
        title={t("teams", "title")}
        count={query.data?.length ?? null}
        description={t("teams", "description")}
        action={
          canManage && (
            <Button onClick={() => setEditing(null)}>
              <Plus className="size-4" />
              {t("squads", "add")}
            </Button>
          )
        }
      />

      {query.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-40" />
          ))}
        </div>
      ) : teams.length === 0 ? (
        <EmptyState
          icon={<Shirt />}
          title={t("teams", "emptyTitle")}
          description={t("teams", "emptyBody")}
          action={
            canManage && (
              <Button onClick={() => setEditing(null)}>{t("squads", "add")}</Button>
            )
          }
        />
      ) : (
        <>
          {senior.length > 0 && (
            <Section title={t("teams", "senior")} description={t("teams", "seniorHint")}>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {senior.map((team) => (
                  <TeamCard
                    key={team.id}
                    team={team}
                    onEdit={canManage ? () => setEditing(team) : undefined}
                  />
                ))}
              </div>
            </Section>
          )}
          {academy.length > 0 && (
            <Section title={t("teams", "academy")} description={t("teams", "academyHint")}>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {academy.map((team) => (
                  <TeamCard
                    key={team.id}
                    team={team}
                    onEdit={canManage ? () => setEditing(team) : undefined}
                  />
                ))}
              </div>
            </Section>
          )}
        </>
      )}

      <TeamEditor
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        team={editing ?? null}
      />
    </div>
  );
}
