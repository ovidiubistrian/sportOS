import { AlertTriangle, ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Inbox, SearchX } from "lucide-react";
import { Fragment, type ReactNode } from "react";

import { Button, Card, Skeleton, cn } from "./primitives";

/* --- PageHeader -----------------------------------------------------------
 *
 * Eyebrow → title → description, with actions on the right. The eyebrow carries
 * the context ("Club · FC Example") so the title itself can stay short.
 */

export function PageHeader({
  eyebrow,
  title,
  count,
  description,
  action,
  meta,
  className,
}: {
  eyebrow?: ReactNode;
  title: string;
  count?: number | null;
  description?: string;
  action?: ReactNode;
  /** Badges or status shown next to the title. */
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-1 flex items-center gap-1.5 text-xs font-medium tracking-wide text-text-tertiary uppercase">
            {eyebrow}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="truncate text-2xl font-semibold text-text">{title}</h1>
          {count != null && (
            <span
              className="rounded-full bg-bg-muted px-2 py-0.5 text-xs font-medium text-text-secondary"
              data-numeric
            >
              {count.toLocaleString()}
            </span>
          )}
          {meta}
        </div>
        {description && (
          <p className="mt-1.5 max-w-2xl text-sm text-text-secondary">{description}</p>
        )}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </header>
  );
}

/* --- Section --------------------------------------------------------------- */

export function Section({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-3", className)}>
      <div className="flex items-end justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-text">{title}</h2>
          {description && (
            <p className="mt-0.5 text-xs text-text-secondary">{description}</p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

/* --- Toolbar ---------------------------------------------------------------
 *
 * Filters on the left, actions on the right, and a single row of height. The
 * discipline matters: filters that wrap onto three lines are how a list view
 * stops feeling like a tool.
 */

export function Toolbar({
  children,
  trailing,
  className,
}: {
  children: ReactNode;
  trailing?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {children}
      {trailing && <div className="ml-auto flex items-center gap-2">{trailing}</div>}
    </div>
  );
}

/* --- StatCard --------------------------------------------------------------
 *
 * One number, large, with its label above it. The number is the content; the
 * label is a caption. Putting the label first and the number in display size is
 * what makes a row of these readable at a glance rather than a grid of boxes.
 */

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = "neutral",
  isLoading,
  href,
  onClick,
}: {
  label: string;
  value: number | string | null | undefined;
  hint?: string;
  icon?: ReactNode;
  tone?: "neutral" | "brand" | "success" | "warning";
  isLoading?: boolean;
  href?: string;
  onClick?: () => void;
}) {
  const tones = {
    neutral: "bg-bg-muted text-text-secondary",
    brand: "bg-brand-subtle text-brand-text",
    success: "bg-success-bg text-success",
    warning: "bg-warning-bg text-warning",
  } as const;

  const interactive = Boolean(href || onClick);

  return (
    <Card
      interactive={interactive}
      className={cn("group relative overflow-hidden p-4", interactive && "cursor-pointer")}
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium tracking-wide text-text-secondary uppercase">
          {label}
        </p>
        {icon && (
          <span
            aria-hidden
            className={cn(
              "grid size-7 shrink-0 place-items-center rounded-md [&_svg]:size-4",
              tones[tone],
            )}
          >
            {icon}
          </span>
        )}
      </div>

      {isLoading ? (
        <Skeleton className="mt-3 h-8 w-20" />
      ) : (
        <p className="display mt-2 text-4xl font-semibold text-text">
          {typeof value === "number" ? value.toLocaleString() : (value ?? "—")}
        </p>
      )}

      {hint && <p className="mt-1 text-xs text-text-tertiary">{hint}</p>}
    </Card>
  );
}

/* --- States ---------------------------------------------------------------- */

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <Card className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <span
        aria-hidden
        className="mb-4 grid size-12 place-items-center rounded-xl bg-bg-muted text-text-tertiary [&_svg]:size-6"
      >
        {icon ?? <Inbox />}
      </span>
      <p className="text-base font-medium text-text">{title}</p>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm text-text-secondary">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </Card>
  );
}

export function NoResultsState({
  onClear,
  title = "Nothing matches those filters",
  description = "Try a broader search, or clear the filters to see everything again.",
  clearLabel = "Clear filters",
}: {
  onClear: () => void;
  title?: string;
  description?: string;
  clearLabel?: string;
}) {
  return (
    <EmptyState
      icon={<SearchX />}
      title={title}
      description={description}
      action={
        <Button variant="secondary" size="sm" onClick={onClear}>
          {clearLabel}
        </Button>
      }
    />
  );
}

export function ErrorState({
  error,
  onRetry,
  title = "Something went wrong",
  retryLabel = "Try again",
}: {
  error: Error & { requestId?: string | null };
  onRetry?: () => void;
  title?: string;
  retryLabel?: string;
}) {
  return (
    <Card className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <span
        aria-hidden
        className="mb-4 grid size-12 place-items-center rounded-xl bg-danger-bg text-danger [&_svg]:size-6"
      >
        <AlertTriangle />
      </span>
      <p className="text-base font-medium text-text">{title}</p>
      <p className="mt-1.5 max-w-md text-sm text-text-secondary">{error.message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-5" onClick={onRetry}>
          {retryLabel}
        </Button>
      )}
      {/* The request id is what turns "it broke" into something supportable. */}
      {error.requestId && (
        <p className="mt-4 font-mono text-xs text-text-tertiary">{error.requestId}</p>
      )}
    </Card>
  );
}

/* --- DataTable -------------------------------------------------------------
 *
 * No zebra striping, no vertical rules. Rows are separated by a hairline and
 * distinguished on hover; anything more competes with the data itself.
 */

export interface Column<T> {
  key: string;
  header: ReactNode;
  width?: string;
  align?: "left" | "right" | "center";
  /** Hides the column below the given breakpoint rather than scrolling it away. */
  hideBelow?: "sm" | "md" | "lg";
  sortable?: boolean;
  render: (row: T) => ReactNode;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  isLoading,
  skeletonRows = 8,
  sort,
  onSortChange,
  className,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  isLoading?: boolean;
  skeletonRows?: number;
  sort?: { key: string; direction: "asc" | "desc" } | null;
  onSortChange?: (key: string) => void;
  className?: string;
}) {
  const hideClass = {
    sm: "hidden sm:table-cell",
    md: "hidden md:table-cell",
    lg: "hidden lg:table-cell",
  } as const;

  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-bg-subtle">
              {columns.map((column) => {
                const active = sort?.key === column.key;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={
                      active
                        ? sort.direction === "asc"
                          ? "ascending"
                          : "descending"
                        : undefined
                    }
                    style={column.width ? { width: column.width } : undefined}
                    className={cn(
                      "px-3 py-2.5 text-xs font-medium tracking-wide text-text-secondary uppercase",
                      column.align === "right"
                        ? "text-right"
                        : column.align === "center"
                          ? "text-center"
                          : "text-left",
                      column.hideBelow && hideClass[column.hideBelow],
                    )}
                  >
                    {column.sortable && onSortChange ? (
                      <button
                        type="button"
                        onClick={() => onSortChange(column.key)}
                        className={cn(
                          "inline-flex items-center gap-1 transition-colors hover:text-text",
                          active && "text-text",
                        )}
                      >
                        {column.header}
                        {active &&
                          (sort.direction === "asc" ? (
                            <ArrowUp className="size-3" />
                          ) : (
                            <ArrowDown className="size-3" />
                          ))}
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {isLoading
              ? // Skeleton rows match the real row height so the layout does
                // not shift when data arrives.
                Array.from({ length: skeletonRows }).map((_, index) => (
                  <tr key={index} className="border-b border-border-subtle last:border-0">
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          "px-3 py-2.5",
                          column.hideBelow && hideClass[column.hideBelow],
                        )}
                      >
                        <Skeleton
                          className="h-4"
                          style={{ width: `${45 + ((index * 13) % 40)}%` }}
                        />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map((row) => (
                  <tr
                    key={rowKey(row)}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    onKeyDown={
                      onRowClick
                        ? (event) => {
                            if (event.key === "Enter") onRowClick(row);
                          }
                        : undefined
                    }
                    tabIndex={onRowClick ? 0 : undefined}
                    className={cn(
                      "border-b border-border-subtle transition-colors last:border-0",
                      onRowClick &&
                        "cursor-pointer hover:bg-surface-hover focus-visible:bg-surface-hover",
                    )}
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          "px-3 py-2.5 text-text",
                          column.align === "right" && "text-right",
                          column.align === "center" && "text-center",
                          column.hideBelow && hideClass[column.hideBelow],
                        )}
                      >
                        {column.render(row)}
                      </td>
                    ))}
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* --- Pagination ------------------------------------------------------------ */

export function Pagination({
  offset,
  limit,
  total,
  isEstimate,
  hasMore,
  onChange,
  ofLabel = "of",
  previousLabel = "Previous page",
  nextLabel = "Next page",
}: {
  offset: number;
  limit: number;
  total?: number | null;
  isEstimate?: boolean;
  hasMore: boolean;
  onChange: (offset: number) => void;
  ofLabel?: string;
  previousLabel?: string;
  nextLabel?: string;
}) {
  const from = total === 0 ? 0 : offset + 1;
  const to = offset + limit;

  return (
    <div className="flex items-center justify-between gap-4 pt-1">
      <p className="text-xs text-text-secondary" data-numeric>
        {from.toLocaleString()}–{Math.min(to, total ?? to).toLocaleString()}
        {total != null && (
          <>
            {` ${ofLabel} `}
            {total.toLocaleString()}
            {/* An estimate is shown as "10,000+" rather than a precise-looking
                number we did not actually compute. */}
            {isEstimate && "+"}
          </>
        )}
      </p>
      <div className="flex items-center gap-1">
        <Button
          variant="secondary"
          size="icon-sm"
          aria-label={previousLabel}
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          <ChevronLeft />
        </Button>
        <Button
          variant="secondary"
          size="icon-sm"
          aria-label={nextLabel}
          disabled={!hasMore}
          onClick={() => onChange(offset + limit)}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}

/* --- DescriptionList ------------------------------------------------------- */

export function DescriptionList({
  items,
  columns = 2,
  className,
}: {
  items: { term: string; value: ReactNode }[];
  columns?: 1 | 2 | 3;
  className?: string;
}) {
  const grid = {
    1: "sm:grid-cols-1",
    2: "sm:grid-cols-2",
    3: "sm:grid-cols-2 lg:grid-cols-3",
  } as const;

  return (
    <dl className={cn("grid grid-cols-1 gap-x-6 gap-y-4", grid[columns], className)}>
      {items.map((item) => (
        <Fragment key={item.term}>
          <div className="min-w-0">
            <dt className="text-xs font-medium tracking-wide text-text-tertiary uppercase">
              {item.term}
            </dt>
            <dd className="mt-1 text-sm text-text">{item.value}</dd>
          </div>
        </Fragment>
      ))}
    </dl>
  );
}
