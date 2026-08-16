import {
  useAssistant,
  useBranding,
  useContentList,
  usePlayers,
  useTeams,
  type ContentSummary,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  Section,
  Skeleton,
  StatCard,
  cn,
} from "@footbola/ui";
import {
  ArrowUpRight,
  ExternalLink,
  Globe,
  Newspaper,
  Palette,
  PenLine,
  Shirt,
  Sparkles,
  UserPlus,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";
import { ARTICLE_TYPE_LABELS, STATUS_TONE } from "./news/labels";
import { clubHostname, clubSiteUrl } from "../app/site-url";

/**
 * The dashboard.
 *
 * Answers three questions, in this order: what is the club, what is the shape
 * of it, and what should I do next. Deliberately not a wall of widgets — every
 * block here is either a number a club actually tracks or a door to work that
 * needs doing.
 */

function ClubBanner() {
  const { me, club } = useSession();
  const { t } = useI18n();
  const branding = useBranding(club.id);
  const siteUrl = clubSiteUrl(club.slug);

  return (
    <Card className="relative overflow-hidden">
      {/* A wide brand wash behind the crest. Contained, low opacity, and behind
          nothing that has to stay readable — which is the only place a club
          colour belongs as a large fill. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-32 opacity-[0.07]"
        style={{
          background:
            "radial-gradient(60% 120% at 20% 0%, var(--brand) 0%, transparent 70%)",
        }}
      />

      <div className="relative flex flex-wrap items-center gap-5 p-5 lg:p-6">
        <span
          aria-hidden
          className="grid size-16 shrink-0 place-items-center rounded-xl bg-brand text-lg font-bold text-brand-contrast shadow-md"
        >
          {club.short_name.slice(0, 3).toUpperCase()}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-2xl font-semibold text-text">
              {club.display_name}
            </h1>
            <Badge tone="brand" size="md">
              {branding.data?.template.toLowerCase() ?? "…"}
            </Badge>
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-text-secondary">
            <span>{me.active_tenant?.legal_name}</span>
            <span aria-hidden className="text-text-disabled">
              ·
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Globe className="size-3.5" />
              {clubHostname(club.slug)}
            </span>
            <span aria-hidden className="text-text-disabled">
              ·
            </span>
            <span>{(me.active_tenant?.supported_locales ?? []).join(" · ").toUpperCase()}</span>
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {siteUrl && (
            <Button variant="secondary" asChild>
              <a href={siteUrl} target="_blank" rel="noreferrer">
                <ExternalLink />
                {t("dashboard", "viewSite")}
              </a>
            </Button>
          )}
          <Button variant="primary" asChild>
            <Link to="/site">
              <Palette />
              {t("dashboard", "customise")}
            </Link>
          </Button>
        </div>
      </div>
    </Card>
  );
}

function QuickAction({
  to,
  icon: Icon,
  title,
  description,
}: {
  to: string;
  icon: typeof Users;
  title: string;
  description: string;
}) {
  return (
    <Link to={to} className="group">
      <Card interactive className="flex h-full items-start gap-3 p-4">
        <span
          aria-hidden
          className="grid size-8 shrink-0 place-items-center rounded-md bg-brand-subtle text-brand-text"
        >
          <Icon className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1 text-sm font-medium text-text">
            {title}
            <ArrowUpRight className="size-3.5 text-text-tertiary opacity-0 transition-opacity group-hover:opacity-100" />
          </span>
          <span className="mt-0.5 block text-xs text-text-secondary">{description}</span>
        </span>
      </Card>
    </Link>
  );
}

function TeamBreakdown() {
  const { t, formatNumber } = useI18n();
  const teams = useTeams();
  const players = usePlayers({ limit: 1, with_total: true });
  const total = players.data?.page.total ?? 0;

  if (teams.isLoading) {
    return (
      <Card className="space-y-3 p-4">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </Card>
    );
  }

  const list = teams.data ?? [];
  if (list.length === 0) {
    return (
      <Card className="p-6 text-center">
        <p className="text-sm text-text-secondary">{t("dashboard", "noTeams")}</p>
      </Card>
    );
  }

  return (
    <Card className="divide-y divide-border-subtle">
      {list.slice(0, 8).map((team) => (
        <Link
          key={team.id}
          to={`/players?team_id=${team.id}`}
          className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-surface-hover"
        >
          <span
            aria-hidden
            className="grid size-7 shrink-0 place-items-center rounded-md bg-bg-muted text-[0.625rem] font-semibold text-text-secondary"
          >
            {team.code}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-text">{team.name}</span>
            <span className="block text-xs text-text-tertiary">
              {[team.age_group, team.gender].filter(Boolean).join(" · ") ||
                t("teams", "senior")}
            </span>
          </span>
          <ArrowUpRight className="size-3.5 shrink-0 text-text-tertiary" />
        </Link>
      ))}
      {total > 0 && (
        <div className="px-4 py-2.5 text-xs text-text-tertiary" data-numeric>
          {t("dashboard", "playersAcrossTeams", {
            players: formatNumber(total),
            teams: list.length,
          })}
        </div>
      )}
    </Card>
  );
}

function RecentNews() {
  const { t, formatRelativeDay } = useI18n();
  const { path } = useSession();
  const news = useContentList({ limit: 5, with_total: false });

  if (news.isLoading) {
    return (
      <Card className="space-y-3 p-4">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </Card>
    );
  }

  const items = news.data?.data ?? [];
  if (items.length === 0) {
    return (
      <Card className="flex flex-col items-center gap-3 p-6 text-center">
        <p className="text-sm text-text-secondary">{t("dashboard", "nothingPublished")}</p>
        <Button variant="secondary" size="sm" asChild>
          <Link to={path("/news/new")}>{t("dashboard", "writeFirst")}</Link>
        </Button>
      </Card>
    );
  }

  return (
    <Card className="divide-y divide-border-subtle">
      {items.map((item: ContentSummary) => (
        <Link
          key={item.id}
          to={`/news/${item.id}`}
          className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-surface-hover"
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-text">{item.title}</span>
            <span className="mt-0.5 flex items-center gap-1.5 text-xs text-text-tertiary">
              <span>{ARTICLE_TYPE_LABELS[item.article_type] ?? item.article_type}</span>
              <span aria-hidden>·</span>
              <span>{formatRelativeDay(item.published_at ?? item.scheduled_for)}</span>
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-1">
            {item.locales.map((locale) => (
              <span
                key={locale.locale}
                title={t("news", locale.is_complete ? "languageReady" : "languageIncomplete", {
                locale: locale.locale.toUpperCase(),
              })}
                className={cn(
                  "rounded px-1 py-0.5 text-[0.625rem] font-medium uppercase",
                  locale.is_complete
                    ? "bg-success-bg text-success"
                    : "bg-warning-bg text-warning",
                )}
              >
                {locale.locale}
              </span>
            ))}
          </span>
          <Badge tone={STATUS_TONE[item.status]} dot>
            {item.status.toLowerCase()}
          </Badge>
        </Link>
      ))}
    </Card>
  );
}

export function OverviewPage() {
  const { can, path } = useSession();
  const { t } = useI18n();
  const players = usePlayers({ limit: 1, with_total: true });
  const teams = useTeams();
  const drafts = useContentList({ status: "DRAFT", limit: 1, with_total: true });
  const assistant = useAssistant();

  const assistantHint = assistant.data?.available
    ? assistant.data.requests_limit == null
      ? "unlimited this month"
      : `${assistant.data.requests_limit - assistant.data.requests_used} left this month`
    : (assistant.data?.reason ?? undefined);

  return (
    <div className="space-y-8">
      <ClubBanner />

      <section aria-label="At a glance" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t("dashboard", "statPlayers")}
          value={players.data?.page.total}
          icon={<Users />}
          tone="brand"
          isLoading={players.isLoading}
          hint={t("dashboard", "statPlayersHint")}
        />
        <StatCard
          label={t("dashboard", "statTeams")}
          value={teams.data?.length}
          icon={<Shirt />}
          isLoading={teams.isLoading}
          hint={t("dashboard", "statTeamsHint")}
        />
        <StatCard
          label={t("dashboard", "statDrafts")}
          value={drafts.data?.page.total}
          icon={<PenLine />}
          tone={drafts.data?.page.total ? "warning" : "neutral"}
          isLoading={drafts.isLoading}
          hint={t("dashboard", "statDraftsHint")}
        />
        <StatCard
          label={t("dashboard", "statAssistant")}
          value={
            assistant.data?.available
              ? (assistant.data.requests_limit ?? "∞")
              : "off"
          }
          icon={<Sparkles />}
          tone={assistant.data?.available ? "success" : "neutral"}
          isLoading={assistant.isLoading}
          hint={assistantHint}
        />
      </section>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Section
          title={t("dashboard", "latestNews")}
          description={t("dashboard", "latestNewsHint")}
          action={
            <Button variant="ghost" size="sm" asChild>
              <Link to={path("/news")}>
                {t("common", "viewAll")}
                <ArrowUpRight />
              </Link>
            </Button>
          }
        >
          <RecentNews />
        </Section>

        <Section
          title={t("dashboard", "squads")}
          description={t("dashboard", "squadsHint")}
          action={
            <Button variant="ghost" size="sm" asChild>
              <Link to={path("/teams")}>
                {t("common", "viewAll")}
                <ArrowUpRight />
              </Link>
            </Button>
          }
        >
          <TeamBreakdown />
        </Section>
      </div>

      <Section
        title={t("dashboard", "getThingsDone")}
        description={t("dashboard", "getThingsDoneHint")}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {can("cms.content.write") && (
            <QuickAction
              to={path("/news/new")}
              icon={Newspaper}
              title={t("dashboard", "writeArticle")}
              description={t("dashboard", "writeArticleHint")}
            />
          )}
          {can("players.player.create") && (
            <QuickAction
              to={path("/players")}
              icon={UserPlus}
              title={t("dashboard", "registerPlayer")}
              description={t("dashboard", "registerPlayerHint")}
            />
          )}
          <QuickAction
            to={path("/site")}
            icon={Palette}
            title={t("dashboard", "changeDesign")}
            description={t("dashboard", "changeDesignHint")}
          />
          <QuickAction
            to={path("/settings")}
            icon={Globe}
            title={t("dashboard", "languagesAndPlan")}
            description={t("dashboard", "languagesAndPlanHint")}
          />
        </div>
      </Section>
    </div>
  );
}
