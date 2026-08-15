import type { ArticleType, ContentStatus, ContentSummary } from "@footbola/api-client";
import { useAssistant, useContentList } from "@footbola/api-client";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  NoResultsState,
  PageHeader,
  Pagination,
  Select,
  Toolbar,
  type Column,
} from "@footbola/ui";
import { Newspaper, PenLine } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";
import { ARTICLE_TYPE_LABELS, STATUS_TONE } from "./labels";

/**
 * The newsroom.
 *
 * Organised by article type as well as status, because a club's news is a
 * handful of recurring kinds — signings, departures, match reports — and
 * "show me every departure" is a question an editor actually asks. The type
 * counters double as the filter.
 */

const PAGE_SIZE = 25;

const STATUSES: ContentStatus[] = [
  "DRAFT",
  "IN_REVIEW",
  "SCHEDULED",
  "PUBLISHED",
  "ARCHIVED",
];

function TranslationCells({ item }: { item: ContentSummary }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap gap-1">
      {item.locales.map((locale) => (
        <Badge
          key={locale.locale}
          tone={locale.is_complete ? "success" : "warning"}
          title={t("news", locale.is_complete ? "languageReady" : "languageIncomplete", {
            locale: locale.locale.toUpperCase(),
          })}
        >
          {locale.locale.toUpperCase()}
        </Badge>
      ))}
    </div>
  );
}

export function NewsListPage() {
  const { can, path, club } = useSession();
  const { t, formatDate } = useI18n();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [offset, setOffset] = useState(0);

  const clubId = club.id;
  const status = (params.get("status") as ContentStatus | null) ?? null;
  const articleType = (params.get("type") as ArticleType | null) ?? null;

  const filters = {
    club_id: clubId,
    status: status ?? undefined,
    article_type: articleType ?? undefined,
    limit: PAGE_SIZE,
    offset,
  };
  const { data, isLoading, error, refetch } = useContentList(filters);
  const rows = data?.data ?? [];
  // Loaded here so the editor's assistant panel is warm by the time it opens,
  // and so "new article" can offer the type skeletons immediately.
  const assistant = useAssistant();

  const update = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setOffset(0);
  };

  const hasFilters = Boolean(status || articleType);

  const columns: Column<ContentSummary>[] = [
    {
      key: "title",
      header: t("news", "columnTitle"),
      render: (item) => (
        <Link
          to={path(`/news/${item.id}`)}
          className="font-medium text-text hover:underline"
        >
          {item.title}
        </Link>
      ),
    },
    {
      key: "article_type",
      header: t("news", "columnType"),
      hideBelow: "md",
      render: (item) => (
        <Badge tone="outline">
          {ARTICLE_TYPE_LABELS[item.article_type] ?? item.article_type}
        </Badge>
      ),
    },
    {
      key: "status",
      header: t("news", "columnStatus"),
      render: (item) => (
        <Badge tone={STATUS_TONE[item.status]} dot>
          {item.status.toLowerCase()}
        </Badge>
      ),
    },
    {
      key: "locales",
      header: t("news", "columnLanguages"),
      hideBelow: "sm",
      render: (item) => <TranslationCells item={item} />,
    },
    {
      key: "when",
      header: t("news", "columnPublished"),
      align: "right",
      hideBelow: "sm",
      render: (item) => (
        <span className="text-text-secondary" data-numeric>
          {item.published_at ?? item.scheduled_for
            ? formatDate((item.published_at ?? item.scheduled_for) as string)
            : "—"}
        </span>
      ),
    },
  ];

  if (error)
    return (
      <ErrorState
        error={error}
        onRetry={() => void refetch()}
        title={t("common", "somethingWentWrong")}
        retryLabel={t("common", "tryAgain")}
      />
    );

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <>
            <Newspaper className="size-3.5" />
            {t("news", "eyebrow")}
          </>
        }
        title={t("news", "title")}
        count={data?.page.total ?? null}
        description={t("news", "description")}
        action={
          can("cms.content.write") ? (
            <Button variant="primary" onClick={() => navigate(path("/news/new"))}>
              <PenLine />
              {t("news", "newArticle")}
            </Button>
          ) : undefined
        }
      />

      <Toolbar>
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
        <div className="w-48">
          <Select
            ariaLabel={t("news", "filterType")}
            value={articleType ?? ""}
            placeholder={t("news", "allTypes")}
            onChange={(value) => update("type", value || null)}
            options={[
              { value: "", label: t("news", "allTypes") },
              ...(assistant.data?.article_types ?? []).map((type) => ({
                value: type.key,
                label: type.name,
                description: type.description,
              })),
            ]}
          />
        </div>
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setParams(new URLSearchParams(), { replace: true });
              setOffset(0);
            }}
          >
            {t("common", "clear")}
          </Button>
        )}
      </Toolbar>

      {!isLoading && rows.length === 0 ? (
        hasFilters ? (
          <NoResultsState
            onClear={() => {
              setParams(new URLSearchParams(), { replace: true });
              setOffset(0);
            }}
            title={t("common", "noResultsTitle")}
            description={t("common", "noResultsBody")}
            clearLabel={t("common", "clearFilters")}
          />
        ) : (
          <EmptyState
            icon={<Newspaper />}
            title={t("news", "emptyTitle")}
            description={t("news", "emptyBody")}
            action={
              can("cms.content.write") ? (
                <Button variant="primary" onClick={() => navigate(path("/news/new"))}>
                  {t("news", "writeFirst")}
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
            rowKey={(item) => item.id}
            isLoading={isLoading}
          />
          {data && (
            <Pagination
              offset={offset}
              limit={PAGE_SIZE}
              total={data.page.total}
              isEstimate={data.page.total_is_estimate}
              hasMore={data.page.has_more}
              ofLabel={t("common", "of")}
              previousLabel={t("common", "previousPage")}
              nextLabel={t("common", "nextPage")}
              onChange={setOffset}
            />
          )}
        </>
      )}
    </div>
  );
}
