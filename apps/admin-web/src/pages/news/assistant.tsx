import type { Block, PolishSuggestion } from "@footbola/api-client";
import {
  ApiError,
  useHeadlines,
  usePolish,
  useRecordOutcome,
  type AssistantStatus,
} from "@footbola/api-client";
import { Badge, Button, Card, Progress } from "@footbola/ui";
import { Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../app/locale";
import { BlockPreview, blockText, pruneBlocks } from "./blocks";

/**
 * The writing assistant panel.
 *
 * Two rules shape this component. The assistant never writes to the article —
 * it returns a proposal that the editor reads side by side and accepts or
 * discards. And it never hides why it is unavailable: a missing button teaches
 * an editor nothing, so an unavailable assistant says which of "not in your
 * plan", "not configured" or "no allowance left" applies.
 */

function changedIndices(before: Block[], after: Block[]): Set<number> {
  const changed = new Set<number>();
  after.forEach((block, index) => {
    if (blockText(block) !== (before[index] ? blockText(before[index]) : undefined)) {
      changed.add(index);
    }
  });
  return changed;
}

function Unavailable({ reason }: { reason: string }) {
  const { t } = useI18n();
  return (
    <Card className="flex items-start gap-2.5 border-dashed p-4">
      <span
        aria-hidden
        className="grid size-7 shrink-0 place-items-center rounded-md bg-bg-muted text-text-tertiary"
      >
        <Sparkles className="size-4" />
      </span>
      <div>
        <p className="text-sm font-medium text-text">{t("assistant", "title")}</p>
        <p className="mt-0.5 text-sm text-text-secondary">{reason}</p>
      </div>
    </Card>
  );
}

function useErrorMessage() {
  const { t } = useI18n();
  return (error: unknown): string => {
    if (!(error instanceof ApiError)) return t("assistant", "unavailable");
    // Codes, never message matching: the wording changes, the contract does not.
    // The API's own message is already in the reader's language for the cases
    // that carry one, so only the codes we phrase ourselves are translated here.
    return error.code === "FEATURE_NOT_ENABLED"
      ? t("assistant", "notInPlan")
      : error.message;
  };
}

export function AssistantPanel({
  status,
  contentItemId,
  locale,
  title,
  blocks,
  onApplyBlocks,
  onApplyTitle,
}: {
  status: AssistantStatus;
  contentItemId: string | null;
  locale: string;
  title: string;
  blocks: Block[];
  onApplyBlocks: (blocks: Block[]) => void;
  onApplyTitle: (title: string) => void;
}) {
  const polish = usePolish();
  const headlines = useHeadlines();
  const outcome = useRecordOutcome();
  const { t } = useI18n();
  const errorMessage = useErrorMessage();
  const [suggestion, setSuggestion] = useState<PolishSuggestion | null>(null);

  if (!status.available) {
    return <Unavailable reason={status.reason ?? t("assistant", "unavailable")} />;
  }

  const body = pruneBlocks(blocks);
  const draftEmpty = body.length === 0 || title.trim().length === 0;
  const request = { content_item_id: contentItemId, locale, title, blocks: body };

  const remaining =
    status.requests_limit == null
      ? null
      : Math.max(0, status.requests_limit - status.requests_used);

  const accept = () => {
    if (!suggestion) return;
    onApplyBlocks(suggestion.blocks);
    outcome.mutate({ usageId: suggestion.usage_id, accepted: true });
    setSuggestion(null);
  };

  const discard = () => {
    if (!suggestion) return;
    outcome.mutate({ usageId: suggestion.usage_id, accepted: false });
    setSuggestion(null);
  };

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5">
          <span
            aria-hidden
            className="grid size-7 shrink-0 place-items-center rounded-md bg-brand-subtle text-brand-text"
          >
            <Sparkles className="size-4" />
          </span>
          <div>
            <p className="text-sm font-medium text-text">{t("assistant", "title")}</p>
            <p className="mt-0.5 text-xs text-text-tertiary">{t("assistant", "tagline")}</p>
          </div>
        </div>
        {remaining != null && (
          <Badge tone={remaining === 0 ? "warning" : "neutral"}>
            <span data-numeric>{remaining}</span>&nbsp;{t("assistant", "left")}
          </Badge>
        )}
      </div>

      {status.requests_limit != null && (
        <Progress
          className="mt-3"
          value={status.requests_used}
          max={status.requests_limit}
          label="Assistant requests used this month"
          tone={remaining === 0 ? "warning" : "brand"}
        />
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          variant="primary"
          size="sm"
          disabled={draftEmpty || polish.isPending}
          onClick={() =>
            polish.mutate(request, { onSuccess: (result) => setSuggestion(result) })
          }
        >
          <Wand2 />
          {polish.isPending ? t("assistant", "improving") : t("assistant", "improve")}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={draftEmpty || headlines.isPending}
          onClick={() => headlines.mutate(request)}
        >
          {headlines.isPending ? t("assistant", "thinking") : t("assistant", "headlines")}
        </Button>
      </div>

      {draftEmpty && (
        <p className="mt-2 text-xs text-text-tertiary">{t("assistant", "emptyDraft")}</p>
      )}

      {(polish.isError || headlines.isError) && (
        <p className="mt-2 text-sm text-danger" role="alert">
          {errorMessage(polish.error ?? headlines.error)}
        </p>
      )}

      {headlines.data && (
        <div className="mt-3">
          <p className="text-xs font-medium uppercase tracking-wide text-text-tertiary">
            {t("assistant", "headlinesTitle")}
          </p>
          <ul className="mt-1.5 space-y-1">
            {headlines.data.headlines.map((option) => (
              <li key={option}>
                <button
                  type="button"
                  className="w-full rounded-sm px-2 py-1.5 text-left text-sm text-text hover:bg-bg-muted"
                  onClick={() => {
                    onApplyTitle(option);
                    outcome.mutate({
                      usageId: headlines.data.usage_id,
                      accepted: true,
                    });
                    headlines.reset();
                  }}
                >
                  {option}
                </button>
              </li>
            ))}
          </ul>
          <Button
            variant="ghost"
            size="sm"
            className="mt-1"
            onClick={() => {
              outcome.mutate({
                usageId: headlines.data.usage_id,
                accepted: false,
              });
              headlines.reset();
            }}
          >
            {t("assistant", "keepMine")}
          </Button>
        </div>
      )}

      {suggestion && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="text-sm text-text">{suggestion.summary_of_changes}</p>

          {/* Side by side, because the editor is accountable for every word
              that gets published under the club's name — including the ones a
              model wrote. Changed blocks are highlighted so the review is a
              scan, not a re-read. */}
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            <div className="rounded-sm border border-border">
              <p className="border-b border-border px-3 py-1.5 text-xs font-medium text-text-tertiary">
                {t("assistant", "yours")}
              </p>
              <BlockPreview blocks={body} />
            </div>
            <div className="rounded-sm border border-border">
              <p className="border-b border-border px-3 py-1.5 text-xs font-medium text-text-tertiary">
                {t("assistant", "suggested")}
              </p>
              <BlockPreview
                blocks={suggestion.blocks}
                changed={changedIndices(body, suggestion.blocks)}
              />
            </div>
          </div>

          <div className="mt-2 flex gap-2">
            <Button variant="primary" size="sm" onClick={accept}>
              {t("assistant", "useSuggestion")}
            </Button>
            <Button variant="ghost" size="sm" onClick={discard}>
              {t("assistant", "keepMine")}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
