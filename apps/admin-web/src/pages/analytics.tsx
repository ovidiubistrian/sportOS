import {
  useAnalytics,
  type AnalyticsCount,
  type AnalyticsFunnelStep,
  type AnalyticsMetric,
  type AnalyticsPoint,
  type AnalyticsRange,
} from "@footbola/api-client";
import {
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Section,
  Segmented,
  Skeleton,
  cn,
} from "@footbola/ui";
import { ArrowDownRight, ArrowUpRight, BarChart3 } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";

/**
 * What the club's website did.
 *
 * Every number is shown against the period immediately before it, because
 * "7,548 sessions" answers nothing on its own — a club wants to know whether
 * the run-in is working, and that is a comparison, not a total.
 *
 * The chart is hand-drawn SVG rather than a charting library. It is forty
 * lines, it inherits the theme's own tokens instead of fighting them, and it
 * spares the admin bundle a dependency whose whole feature set is one bar
 * chart and a tooltip.
 */

const RANGES: AnalyticsRange[] = ["today", "7d", "30d", "90d"];

function Delta({ metric }: { metric: AnalyticsMetric }) {
  const { t } = useI18n();
  if (metric.change_percent === null) {
    // No previous period to compare against. An arrow here would be inventing
    // a trend out of a first week.
    return <p className="mt-1 text-xs text-text-tertiary">{t("analytics", "noComparison")}</p>;
  }

  const up = metric.change_percent >= 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <p
      className={cn(
        "mt-1 flex items-center gap-1 text-xs",
        up ? "text-success" : "text-danger",
      )}
    >
      <Icon className="size-3.5" />
      <span className="font-medium">{Math.abs(metric.change_percent)}%</span>
      <span className="text-text-tertiary">{t("analytics", "vsPrevious")}</span>
    </p>
  );
}

function Stat({
  label,
  value,
  metric,
  live,
}: {
  label: string;
  value: string;
  metric?: AnalyticsMetric;
  live?: boolean;
}) {
  return (
    <Card className="p-4">
      <p className="flex items-center gap-1.5 text-[0.6875rem] font-medium tracking-wider text-text-secondary uppercase">
        {live && (
          <span aria-hidden className="size-1.5 rounded-full bg-success motion-safe:animate-pulse" />
        )}
        {label}
      </p>
      <p className="display mt-2 text-3xl font-semibold tabular-nums text-text">{value}</p>
      {metric && <Delta metric={metric} />}
    </Card>
  );
}

/** Sessions and views per day, side by side. */
function TrafficChart({ series, labels }: { series: AnalyticsPoint[]; labels: [string, string] }) {
  const peak = Math.max(1, ...series.map((point) => Math.max(point.sessions, point.views)));
  const width = Math.max(series.length * 26, 120);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} 120`}
        preserveAspectRatio="none"
        className="h-48 w-full min-w-[32rem]"
        role="img"
        aria-label={`${labels[0]} / ${labels[1]}`}
      >
        {series.map((point, index) => {
          const x = index * 26 + 6;
          const sessions = (point.sessions / peak) * 104;
          const views = (point.views / peak) * 104;
          return (
            <g key={point.day}>
              <title>{`${point.day} · ${labels[0]}: ${point.sessions} · ${labels[1]}: ${point.views}`}</title>
              <rect
                x={x}
                y={112 - sessions}
                width={8}
                height={Math.max(sessions, 1)}
                rx={2}
                className="fill-brand"
              />
              <rect
                x={x + 10}
                y={112 - views}
                width={8}
                height={Math.max(views, 1)}
                rx={2}
                className="fill-text-tertiary/45"
              />
            </g>
          );
        })}
        <line x1="0" y1="113" x2={width} y2="113" className="stroke-border" strokeWidth="1" />
      </svg>

      <div className="mt-3 flex items-center gap-4 text-xs text-text-secondary">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-2 rounded-sm bg-brand" />
          {labels[0]}
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-2 rounded-sm bg-text-tertiary/45" />
          {labels[1]}
        </span>
      </div>
    </div>
  );
}

/** A ranked list with the bar drawn behind the row, not beside it. */
function Ranked({ title, rows, empty }: { title: string; rows: AnalyticsCount[]; empty: string }) {
  const peak = Math.max(1, ...rows.map((row) => row.value));
  return (
    <Card className="p-4">
      <p className="mb-3 text-sm font-medium text-text">{title}</p>
      {rows.length === 0 ? (
        <p className="text-xs text-text-tertiary">{empty}</p>
      ) : (
        <ul className="space-y-1">
          {rows.map((row) => (
            <li key={row.label} className="relative flex items-center justify-between gap-3 rounded-md px-2 py-1.5">
              <span
                aria-hidden
                className="absolute inset-y-0 left-0 rounded-md bg-brand-subtle"
                style={{ width: `${(row.value / peak) * 100}%` }}
              />
              <span className="relative min-w-0 truncate text-sm text-text">
                {row.label}
                {row.unique !== null && (
                  <span className="ml-2 text-xs text-text-tertiary">
                    {row.unique} unici
                  </span>
                )}
              </span>
              <span className="relative shrink-0 text-sm font-medium tabular-nums text-text">
                {row.value}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Funnel({ steps, labels }: { steps: AnalyticsFunnelStep[]; labels: Record<string, string> }) {
  const { t } = useI18n();
  return (
    <Card className="p-4">
      <p className="text-sm font-medium text-text">{t("analytics", "funnel")}</p>
      <p className="mt-0.5 mb-4 text-xs text-text-secondary">{t("analytics", "funnelHint")}</p>
      <ol className="space-y-3">
        {steps.map((step, index) => (
          <li key={step.label}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="text-text">
                <span className="mr-2 text-xs text-text-tertiary">{index + 1}</span>
                {labels[step.label] ?? step.label}
              </span>
              <span className="flex items-baseline gap-2">
                <span className="font-medium tabular-nums text-text">{step.value}</span>
                <span className="text-xs text-text-tertiary">{step.of_total_percent}%</span>
              </span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-bg-muted">
              <div
                className="h-full rounded-full bg-brand"
                style={{ width: `${Math.max(step.of_total_percent, 1)}%` }}
              />
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function AnalyticsPage() {
  const { t, formatNumber } = useI18n();
  const { club } = useSession();
  const [range, setRange] = useState<AnalyticsRange>("30d");
  const query = useAnalytics(range, club?.id);

  if (query.isError) {
    return (
      <ErrorState
        error={Object.assign(new Error(query.error.message), {
          requestId: query.error.requestId,
        })}
        onRetry={() => void query.refetch()}
        title={t("common", "somethingWentWrong")}
        retryLabel={t("common", "tryAgain")}
      />
    );
  }

  const data = query.data;
  const nothingYet = data && data.views.value === 0 && data.views.previous === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("analytics", "eyebrow")}
        title={t("analytics", "title")}
        description={t("analytics", "description")}
        action={
          <Segmented
            ariaLabel={t("analytics", "range")}
            value={range}
            onChange={(next) => setRange(next as AnalyticsRange)}
            options={RANGES.map((key) => ({
              value: key,
              label: t("analytics", `range${key}` as "range30d"),
            }))}
          />
        }
      />

      {!data ? (
        <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-24 w-full" />
          ))}
        </div>
      ) : nothingYet ? (
        <EmptyState
          icon={<BarChart3 className="size-5" />}
          title={t("analytics", "emptyTitle")}
          description={t("analytics", "emptyBody")}
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
            <Stat label={t("analytics", "live")} value={formatNumber(data.live)} live />
            <Stat
              label={t("analytics", "sessions")}
              value={formatNumber(data.sessions.value)}
              metric={data.sessions}
            />
            <Stat
              label={t("analytics", "visitors")}
              value={formatNumber(data.visitors.value)}
              metric={data.visitors}
            />
            <Stat
              label={t("analytics", "views")}
              value={formatNumber(data.views.value)}
              metric={data.views}
            />
            <Stat
              label={t("analytics", "signups")}
              value={formatNumber(data.signups.value)}
              metric={data.signups}
            />
          </div>

          <Section title={t("analytics", "traffic")}>
            <Card className="p-4">
              <TrafficChart
                series={data.series}
                labels={[t("analytics", "sessions"), t("analytics", "views")]}
              />
            </Card>
          </Section>

          <div className="grid gap-4 lg:grid-cols-3">
            <Funnel
              steps={data.funnel}
              labels={{
                visits: t("analytics", "stepVisits"),
                shop: t("analytics", "stepShop"),
                checkout: t("analytics", "stepCheckout"),
                orders: t("analytics", "stepOrders"),
              }}
            />
            <Ranked
              title={t("analytics", "sources")}
              rows={data.sources}
              empty={t("analytics", "sourcesEmpty")}
            />
            <Ranked
              title={t("analytics", "pages")}
              rows={data.pages}
              empty={t("analytics", "noData")}
            />
          </div>

          {/* Only drawn when a geography database is installed. Two empty
              panels would say "this feature is broken" rather than "this
              deployment chose not to ship 120MB of city data". */}
          {(data.countries.length > 0 || data.cities.length > 0) && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Ranked
                title={t("analytics", "countries")}
                rows={data.countries}
                empty={t("analytics", "noData")}
              />
              <Ranked
                title={t("analytics", "cities")}
                rows={data.cities}
                empty={t("analytics", "noData")}
              />
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Ranked
              title={t("analytics", "devices")}
              rows={data.devices}
              empty={t("analytics", "noData")}
            />
            <Ranked
              title={t("analytics", "browsers")}
              rows={data.browsers}
              empty={t("analytics", "noData")}
            />
            <Ranked
              title={t("analytics", "campaigns")}
              rows={data.campaigns}
              empty={t("analytics", "campaignsEmpty")}
            />
          </div>

          <p className="text-xs text-text-tertiary">{t("analytics", "privacy")}</p>
        </>
      )}
    </div>
  );
}
