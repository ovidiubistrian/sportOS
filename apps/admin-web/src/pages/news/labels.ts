import type { ArticleType, ContentStatus } from "@footbola/api-client";

/**
 * Display labels for the newsroom.
 *
 * The authoritative list of article types comes from the API (it carries the
 * skeletons and the assistant's instructions, which only the server knows).
 * These are the local fallbacks, so a list renders correctly before the
 * assistant status has loaded.
 */

export const ARTICLE_TYPE_LABELS: Record<ArticleType, string> = {
  ANNOUNCEMENT: "Announcement",
  MATCH_REPORT: "Match report",
  MATCH_PREVIEW: "Match preview",
  SIGNING: "New signing",
  DEPARTURE: "Departure",
  ACADEMY: "Academy",
  INTERVIEW: "Interview",
};

export const STATUS_TONE: Record<
  ContentStatus,
  "neutral" | "success" | "warning" | "info"
> = {
  DRAFT: "neutral",
  IN_REVIEW: "info",
  SCHEDULED: "warning",
  PUBLISHED: "success",
  ARCHIVED: "neutral",
};
