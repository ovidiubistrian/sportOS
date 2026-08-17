import {
  ApiError,
  useConfigurationReview,
  useForkConfiguration,
  usePublishConfiguration,
  useStadiumLayout,
  useVenueConfigurations,
  useVenues,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Select,
  Skeleton,
  StatCard,
  useToast,
} from "@footbola/ui";
import { AlertTriangle, CheckCircle2, LandPlot, Lock } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";
import { StadiumMap } from "./stadium-map";

/**
 * The stadium: what the club drew, what it adds up to, and what is wrong with it.
 *
 * The screen is built around one idea that is easy to miss and expensive to
 * get wrong — a published configuration is *frozen*. So the publish button is
 * not a save button, and the page says so before it is pressed: matches take
 * their own copy of this layout, and editing afterwards makes a new version
 * rather than changing the one matches were sold from.
 *
 * The review panel shows warnings and errors differently on purpose. A sector
 * with no price zone is a warning — a club halfway through setting up should
 * not be blocked by its own unfinished work — while a layout that sells
 * nothing is an error, because publishing it would produce a match nobody can
 * attend.
 */

export function StadiumPage() {
  const { t } = useI18n();
  const { club } = useSession();
  const toast = useToast();

  const venues = useVenues(club.id);
  const [venueId, setVenueId] = useState<string>();
  const [configId, setConfigId] = useState<string>();

  const configurations = useVenueConfigurations(venueId);
  const layout = useStadiumLayout(configId);
  const review = useConfigurationReview(configId);
  const publish = usePublishConfiguration();
  const fork = useForkConfiguration();

  // Pick something sensible the moment the data lands, so the page is never a
  // set of empty dropdowns waiting to be told what to show.
  useEffect(() => {
    const first = venues.data?.[0];
    if (!venueId && first) setVenueId(first.id);
  }, [venues.data, venueId]);

  useEffect(() => {
    if (!configurations.data?.length) return;
    if (configId && configurations.data.some((c) => c.id === configId)) return;
    const chosen =
      configurations.data.find((c) => c.status === "PUBLISHED") ?? configurations.data[0];
    if (chosen) setConfigId(chosen.id);
  }, [configurations.data, configId]);

  const configuration = configurations.data?.find((c) => c.id === configId);
  const isDraft = configuration?.status === "DRAFT";

  const mapLabels = useMemo(
    () => ({
      zoomIn: t("ticketing", "zoomIn"),
      zoomOut: t("ticketing", "zoomOut"),
      reset: t("ticketing", "resetView"),
      seats: t("ticketing", "seats"),
      gate: t("ticketing", "gate"),
    }),
    [t],
  );

  const errors = review.data?.findings.filter((f) => f.severity === "ERROR") ?? [];
  const warnings = review.data?.findings.filter((f) => f.severity === "WARNING") ?? [];

  const onPublish = async () => {
    if (!configId) return;
    try {
      await publish.mutateAsync(configId);
      toast.success(t("ticketing", "publishedToast"));
    } catch (error) {
      if (error instanceof ApiError) {
        toast.error(t("ticketing", "cannotPublish"), error.message);
      }
    }
  };

  const onFork = async () => {
    if (!configId) return;
    try {
      const draft = await fork.mutateAsync(configId);
      setConfigId(draft.id);
      toast.success(t("ticketing", "forkedToast"));
    } catch (error) {
      if (error instanceof ApiError) toast.error(error.message);
    }
  };

  if (venues.isLoading) return <Skeleton className="h-96" />;

  if (!venues.data?.length) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={
            <>
              <LandPlot className="size-3.5" />
              {t("ticketing", "eyebrow")}
            </>
          }
          title={t("ticketing", "stadiumTitle")}
          description={t("ticketing", "stadiumDescription")}
        />
        <EmptyState
          title={t("ticketing", "noStadium")}
          description={t("ticketing", "noStadiumHint")}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <>
            <LandPlot className="size-3.5" />
            {t("ticketing", "eyebrow")}
          </>
        }
        title={t("ticketing", "stadiumTitle")}
        description={t("ticketing", "stadiumDescription")}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={venueId ?? ""}
              onChange={(value) => {
                setVenueId(value);
                setConfigId(undefined);
              }}
              options={(venues.data ?? []).map((venue) => ({
                value: venue.id,
                label: venue.name,
              }))}
            />
            <Select
              value={configId ?? ""}
              onChange={setConfigId}
              options={(configurations.data ?? []).map((config) => ({
                value: config.id,
                label: `${config.name} · v${config.version}`,
              }))}
            />
          </div>
        }
      />

      {configuration && (
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={isDraft ? "outline" : "success"} dot>
            {isDraft
              ? t("ticketing", "draft")
              : configuration.status === "PUBLISHED"
                ? t("ticketing", "published")
                : t("ticketing", "archived")}
          </Badge>
          <span className="text-sm text-text-secondary">
            {t("ticketing", "version")} {configuration.version}
          </span>

          {isDraft ? (
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                loading={publish.isPending}
                disabled={errors.length > 0}
                onClick={onPublish}
              >
                {t("ticketing", "publish")}
              </Button>
              <span className="text-xs text-text-tertiary">
                {t("ticketing", "publishHint")}
              </span>
            </div>
          ) : (
            <Button variant="secondary" loading={fork.isPending} onClick={onFork}>
              <Lock className="size-4" />
              {t("ticketing", "newVersion")}
            </Button>
          )}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="p-4">
          {layout.isLoading ? (
            <Skeleton className="aspect-square w-full" />
          ) : layout.data ? (
            <StadiumMap layout={layout.data} labels={mapLabels} tone="zone" />
          ) : (
            <EmptyState
              title={t("ticketing", "noStadium")}
              description={t("ticketing", "noStadiumHint")}
            />
          )}
        </Card>

        <div className="space-y-4">
          {review.isLoading ? (
            <Skeleton className="h-64" />
          ) : review.data ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <StatCard
                  label={t("ticketing", "capacity")}
                  value={review.data.total_capacity.toLocaleString()}
                />
                <StatCard
                  label={t("ticketing", "reservedSeats")}
                  value={review.data.reserved_seats.toLocaleString()}
                />
                <StatCard
                  label={t("ticketing", "generalAdmission")}
                  value={review.data.general_admission.toLocaleString()}
                />
                <StatCard
                  label={t("ticketing", "accessibleSeats")}
                  value={review.data.accessible_seats.toLocaleString()}
                />
              </div>

              <Card className="p-4">
                <p className="text-sm font-medium text-text">{t("ticketing", "byStand")}</p>
                <ul className="mt-3 space-y-2">
                  {review.data.by_stand.map((stand) => (
                    <li
                      key={stand.id}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-text-secondary">{stand.name}</span>
                      <span className="font-medium text-text" data-numeric>
                        {stand.capacity.toLocaleString()}
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>

              <Card className="p-4">
                <p className="text-sm font-medium text-text">{t("ticketing", "warnings")}</p>
                {errors.length === 0 && warnings.length === 0 ? (
                  <p className="mt-2 flex items-center gap-2 text-sm text-success">
                    <CheckCircle2 className="size-4" />
                    {t("ticketing", "noWarnings")}
                  </p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {[...errors, ...warnings].map((finding, index) => (
                      <li
                        key={`${finding.code}-${index}`}
                        className="flex items-start gap-2 text-sm"
                      >
                        <AlertTriangle
                          className={
                            finding.severity === "ERROR"
                              ? "mt-0.5 size-4 shrink-0 text-danger"
                              : "mt-0.5 size-4 shrink-0 text-warning"
                          }
                        />
                        <span className="text-text-secondary">{finding.message}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
