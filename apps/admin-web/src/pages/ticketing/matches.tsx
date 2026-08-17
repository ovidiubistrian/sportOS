import {
  useEventLayout,
  useEventReport,
  useTicketedEvents,
  type SectionAvailability,
} from "@footbola/api-client";
import {
  Badge,
  Card,
  EmptyState,
  PageHeader,
  Progress,
  Skeleton,
  StatCard,
} from "@footbola/ui";
import { Ticket } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";
import { StadiumMap } from "./stadium-map";

/**
 * Matches on sale, and how each one is going.
 *
 * The map here is coloured by *availability*, not by price zone — the question
 * on a Thursday is which parts of the ground are not moving, and a map that
 * repeats the price bands answers a question nobody is asking at that point.
 *
 * The layout is read from the match's own snapshot rather than from the
 * stadium master. That is not an implementation detail worth hiding: it is why
 * a report run next season still shows the ground as it was on the day.
 */

function money(minor: number, currency: string): string {
  return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(minor / 100);
}

export function MatchesPage() {
  const { t } = useI18n();
  const { club } = useSession();

  const events = useTicketedEvents(club.id);
  const [eventId, setEventId] = useState<string>();

  const layout = useEventLayout(eventId);
  const report = useEventReport(eventId);

  useEffect(() => {
    const first = events.data?.[0];
    if (!eventId && first) setEventId(first.id);
  }, [events.data, eventId]);

  const selected = events.data?.find((event) => event.id === eventId);

  const mapLabels = useMemo(
    () => ({
      zoomIn: t("ticketing", "zoomIn"),
      zoomOut: t("ticketing", "zoomOut"),
      reset: t("ticketing", "resetView"),
      seats: t("ticketing", "seats"),
      gate: t("ticketing", "gate"),
      available: t("ticketing", "available"),
      filling: t("ticketing", "filling"),
      almostGone: t("ticketing", "almostGone"),
      unavailable: t("ticketing", "unavailable"),
    }),
    [t],
  );

  // Sector id -> how free it is, which is what colours the map.
  const statuses = useMemo(() => {
    const out: Record<string, { ratio: number; label: string }> = {};
    for (const row of layout.data?.availability ?? []) {
      const availability: SectionAvailability = row;
      out[availability.section_id] = {
        ratio: availability.total ? availability.available / availability.total : 0,
        label: `${availability.available}/${availability.total}`,
      };
    }
    return out;
  }, [layout.data]);

  if (events.isLoading) return <Skeleton className="h-96" />;

  if (!events.data?.length) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={
            <>
              <Ticket className="size-3.5" />
              {t("ticketing", "eyebrow")}
            </>
          }
          title={t("ticketing", "matchesTitle")}
          description={t("ticketing", "matchesDescription")}
        />
        <EmptyState
          title={t("ticketing", "noMatches")}
          description={t("ticketing", "noMatchesHint")}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <>
            <Ticket className="size-3.5" />
            {t("ticketing", "eyebrow")}
          </>
        }
        title={t("ticketing", "matchesTitle")}
        description={t("ticketing", "matchesDescription")}
      />

      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card className="p-2">
          <ul>
            {events.data.map((event) => (
              <li key={event.id}>
                <button
                  type="button"
                  onClick={() => setEventId(event.id)}
                  aria-current={event.id === eventId}
                  className={`w-full rounded-lg px-3 py-2.5 text-left transition-colors ${
                    event.id === eventId ? "bg-surface-2" : "hover:bg-surface-2/60"
                  }`}
                >
                  <span className="block truncate text-sm font-medium text-text">
                    {event.name}
                  </span>
                  <span className="mt-0.5 flex items-center gap-2">
                    <span className="text-xs text-text-secondary">
                      {new Date(event.kickoff_at).toLocaleDateString()}
                    </span>
                    <Badge
                      tone={event.status === "PUBLISHED" ? "success" : "outline"}
                      size="sm"
                    >
                      {event.status === "PUBLISHED"
                        ? t("ticketing", "published")
                        : t("ticketing", "draft")}
                    </Badge>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-5">
          {report.isLoading || !report.data ? (
            <Skeleton className="h-32" />
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard
                  label={t("ticketing", "sold")}
                  value={report.data.capacity.sold.toLocaleString()}
                />
                <StatCard
                  label={t("ticketing", "available")}
                  value={report.data.capacity.available.toLocaleString()}
                />
                <StatCard
                  label={t("ticketing", "ticketsIssued")}
                  value={report.data.tickets_issued.toLocaleString()}
                />
                <StatCard
                  label={t("ticketing", "grossRevenue")}
                  value={money(
                    report.data.revenue.gross_minor,
                    selected?.currency ?? "RON",
                  )}
                />
              </div>

              <Card className="p-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-text">
                    {t("ticketing", "occupancy")}
                  </p>
                  <span className="text-sm text-text-secondary" data-numeric>
                    {Math.round(report.data.capacity.occupancy * 100)}%
                  </span>
                </div>
                <Progress
                  className="mt-2"
                  value={Math.round(report.data.capacity.occupancy * 100)}
                />
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-text-secondary">
                  <span>
                    {t("ticketing", "held")}: {report.data.capacity.held}
                  </span>
                  <span>
                    {t("ticketing", "allocated")}: {report.data.capacity.allocated}
                  </span>
                  <span>
                    {t("ticketing", "blockedSeats")}: {report.data.capacity.blocked}
                  </span>
                  <span>
                    {t("ticketing", "seasonTickets")}: {report.data.season_tickets}
                  </span>
                </div>
              </Card>
            </>
          )}

          <Card className="p-4">
            {layout.isLoading ? (
              <Skeleton className="aspect-square w-full" />
            ) : layout.data ? (
              <StadiumMap
                layout={layout.data.payload}
                labels={mapLabels}
                tone="availability"
                statuses={statuses}
              />
            ) : null}
          </Card>

          {report.data && report.data.by_ticket_type.length > 0 && (
            <Card className="p-4">
              <p className="text-sm font-medium text-text">
                {t("ticketing", "byTicketType")}
              </p>
              <ul className="mt-3 divide-y divide-border">
                {report.data.by_ticket_type.map((row) => (
                  <li
                    key={row.ticket_type}
                    className="flex items-center justify-between py-2 text-sm"
                  >
                    <span className="text-text-secondary">{row.ticket_type}</span>
                    <span className="flex items-center gap-4">
                      <span data-numeric className="text-text-tertiary">
                        {row.count}
                      </span>
                      <span data-numeric className="font-medium text-text">
                        {money(row.gross_minor, selected?.currency ?? "RON")}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
