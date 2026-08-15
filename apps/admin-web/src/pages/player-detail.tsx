import { usePlayer } from "@footbola/api-client";
import {
  Avatar,
  Badge,
  Button,
  Card,
  DescriptionList,
  ErrorState,
  Section,
  Skeleton,
} from "@footbola/ui";
import { ChevronLeft, Pencil, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";
import { PlayerEditor } from "./player-editor";

const STATUS_TONE = {
  REGISTERED: "success",
  TRIAL: "warning",
  LOANED_OUT: "info",
  INACTIVE: "neutral",
  DEPARTED: "neutral",
} as const;

export function PlayerDetailPage() {
  const { playerId = "" } = useParams();
  const { path, can } = useSession();
  const { t } = useI18n();
  const canManage = can("players.player.update");
  const [editing, setEditing] = useState(false);
  const query = usePlayer(playerId);

  if (query.isError) {
    // 404 here means "does not exist, or is outside your scope" — the API
    // deliberately does not distinguish the two.
    return (
      <ErrorState
        error={Object.assign(
          new Error(
            query.error.status === 404
              ? t("players", "notFound")
              : query.error.message,
          ),
          { requestId: query.error.requestId },
        )}
        onRetry={() => void query.refetch()}
      />
    );
  }

  if (query.isLoading || !query.data) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-24 w-full" />
        <div className="grid gap-6 lg:grid-cols-2">
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
        </div>
      </div>
    );
  }

  const player = query.data;

  return (
    <div className="space-y-8">
      <Link
        to={path("/players")}
        className="inline-flex items-center gap-1 text-xs text-text-secondary transition-colors hover:text-text"
      >
        <ChevronLeft className="size-3.5" />
        {t("players", "title")}
      </Link>

      <Card className="flex flex-wrap items-center gap-5 p-5">
        <Avatar name={player.display_name} size="xl" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="truncate text-2xl font-semibold text-text">
              {player.display_name}
            </h1>
            {player.shirt_number != null && (
              <span
                className="display rounded-md bg-bg-muted px-2 py-0.5 text-lg font-semibold text-text-secondary"
                data-numeric
              >
                {player.shirt_number}
              </span>
            )}
            <Badge tone={STATUS_TONE[player.status] ?? "neutral"} dot size="md">
              {player.status.replace("_", " ").toLowerCase()}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-text-secondary">
            {[player.team?.name, player.primary_position].filter(Boolean).join(" · ") ||
              t("players", "unassigned")}
          </p>
        </div>
        {canManage && (
          <Button variant="secondary" onClick={() => setEditing(true)}>
            <Pencil />
            {t("common", "edit")}
          </Button>
        )}
      </Card>

      <div className="grid gap-8 lg:grid-cols-2">
        <Section
          title={t("players", "registration")}
          description={t("players", "registrationHint")}
        >
          <Card className="p-5">
            <DescriptionList
              columns={2}
              items={[
                {
                  term: t("players", "columnTeam"),
                  value: player.team?.name ?? t("players", "unassigned"),
                },
                {
                  term: t("players", "shirtNumber"),
                  value: <span data-numeric>{player.shirt_number ?? "—"}</span>,
                },
                {
                  term: t("players", "joinedClub"),
                  value: <span data-numeric>{player.joined_club_on ?? "—"}</span>,
                },
                {
                  term: t("players", "federationId"),
                  value: player.federation_id ?? "—",
                },
              ]}
            />
          </Card>
        </Section>

        <Section title={t("players", "profile")} description={t("players", "profileHint")}>
          <Card className="p-5">
            <DescriptionList
              columns={2}
              items={[
                {
                  term: t("players", "dateOfBirth"),
                  value: <span data-numeric>{player.birth_date ?? "—"}</span>,
                },
                {
                  term: t("players", "nationality"),
                  value: player.nationality.length ? player.nationality.join(", ") : "—",
                },
                {
                  term: t("players", "preferredFoot"),
                  value: player.preferred_foot?.toLowerCase() ?? "—",
                },
                {
                  term: t("players", "positions"),
                  value:
                    [player.primary_position, ...player.secondary_positions]
                      .filter(Boolean)
                      .join(", ") || "—",
                },
              ]}
            />
          </Card>
        </Section>
      </div>

      {/* Stated rather than merely absent: a coach opening this page should
          know medical data exists and is deliberately not here, not assume the
          club never recorded any.
          See docs/architecture/06-authorization.md §5. */}
      <Card className="flex items-start gap-3 border-dashed p-4">
        <span
          aria-hidden
          className="grid size-8 shrink-0 place-items-center rounded-md bg-bg-muted text-text-tertiary"
        >
          <ShieldCheck className="size-4" />
        </span>
        <div>
          <p className="text-sm font-medium text-text">{t("players", "medicalTitle")}</p>
          <p className="mt-0.5 text-sm text-text-secondary">
            {t("players", "medicalBody")}
          </p>
        </div>
      </Card>

      {canManage && (
        <PlayerEditor open={editing} onOpenChange={setEditing} player={player} />
      )}
    </div>
  );
}
