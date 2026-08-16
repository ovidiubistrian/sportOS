import type {
  ArticleType,
  Block,
  ContentDetail,
  ContentStatus,
  MediaAsset,
  TranslationDetail,
} from "@footbola/api-client";
import {
  ApiError,
  useAssistant,
  useContent,
  useUpdateContentItem,
  useCreateContent,
  useSaveTranslation,
  useTransitionContent,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Textarea,
  cn,
  useToast,
} from "@footbola/ui";
import {
  Calendar,
  ChevronLeft,
  Newspaper,
  Save,
  Send,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";
import { ImageField } from "../site/image-field";
import { AssistantPanel } from "./assistant";
import { BlockEditor, pruneBlocks } from "./blocks";
import { ARTICLE_TYPE_LABELS, STATUS_TONE } from "./labels";

/**
 * The article editor.
 *
 * One article, many languages: the language tabs edit translations of the same
 * item, and the item's status is shared. That split is what makes "published in
 * Romanian, still being translated into German" a state the editor can see and
 * work with, rather than two half-articles.
 */

interface Draft {
  title: string;
  excerpt: string;
  blocks: Block[];
}

const EMPTY_DRAFT: Draft = { title: "", excerpt: "", blocks: [] };

/** `TranslationInput.excerpt` in app/cms/schemas.py. */
const EXCERPT_MAX = 600;

/**
 * The label on the field the server refused, as a catalogue key.
 *
 * Both spellings of each path: saving a translation puts the field at the top
 * of the body, creating an article nests it under `translation`. A path with
 * no label falls back to the path itself — worse than a label, much better
 * than "something is wrong".
 */
function fieldLabelKey(field: string): "articleTitle" | "summary" | null {
  switch (field) {
    case "title":
    case "translation.title":
      return "articleTitle";
    case "excerpt":
    case "translation.excerpt":
      return "summary";
    default:
      return null;
  }
}

function toDraft(translation: TranslationDetail | undefined): Draft {
  if (!translation) return EMPTY_DRAFT;
  return {
    title: translation.title,
    excerpt: translation.excerpt ?? "",
    blocks: translation.body,
  };
}

/** Which transitions the API will accept from here — the same table it uses. */
const NEXT_STATUS: Record<ContentStatus, ContentStatus[]> = {
  DRAFT: ["IN_REVIEW", "SCHEDULED", "PUBLISHED"],
  IN_REVIEW: ["DRAFT", "SCHEDULED", "PUBLISHED"],
  SCHEDULED: ["DRAFT", "PUBLISHED"],
  PUBLISHED: ["ARCHIVED"],
  ARCHIVED: ["DRAFT"],
};

/** Catalogue keys, so the transition table stays language-free. */
const ACTION_KEYS = {
  DRAFT: "backToDraft",
  IN_REVIEW: "sendForReview",
  SCHEDULED: "schedule",
  PUBLISHED: "publishNow",
  ARCHIVED: "archive",
} as const;

function TypePicker({
  value,
  onChange,
  types,
  disabled,
}: {
  value: ArticleType;
  onChange: (type: ArticleType, skeleton: Block[]) => void;
  types: { key: ArticleType; name: string; description: string; skeleton: Block[] }[];
  disabled?: boolean;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {types.map((type) => (
        <button
          key={type.key}
          type="button"
          disabled={disabled}
          onClick={() => onChange(type.key, type.skeleton)}
          className={cn(
            "rounded-sm border p-3 text-left transition-colors",
            "disabled:cursor-not-allowed disabled:opacity-60",
            value === type.key
              ? "border-brand bg-brand-subtle"
              : "border-border bg-surface hover:bg-surface-hover",
          )}
        >
          <span className="block text-sm font-medium text-text">{type.name}</span>
          <span className="mt-0.5 block text-xs text-text-secondary">
            {type.description}
          </span>
        </button>
      ))}
    </div>
  );
}

export function NewsEditorPage() {
  const { itemId } = useParams<{ itemId: string }>();
  const isNew = itemId === "new" || itemId === undefined;
  const navigate = useNavigate();
  const toast = useToast();
  const { me, can, path } = useSession();
  const { t } = useI18n();

  const clubId = me.clubs[0]?.id ?? "";
  const locales = me.active_tenant?.supported_locales?.length
    ? me.active_tenant.supported_locales
    : [me.active_tenant?.default_locale ?? "en"];


  const [locale, setLocale] = useState<string>(locales[0] ?? "en");
  const [articleType, setArticleType] = useState<ArticleType>("ANNOUNCEMENT");
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [dirty, setDirty] = useState(false);
  const [scheduledFor, setScheduledFor] = useState("");
  // Only until the article exists. From then on the saved item is the truth
  // and the cover is edited straight against it.
  const [newCover, setNewCover] = useState<MediaAsset | null>(null);

  const query = useContent(isNew ? null : (itemId ?? null));
  const assistant = useAssistant();
  const create = useCreateContent();
  const save = useSaveTranslation(itemId ?? "");
  const transition = useTransitionContent(itemId ?? "");

  const item: ContentDetail | undefined = query.data;
  const cover = useUpdateContentItem();
  const translation = item?.translations.find((t) => t.locale === locale);

  // Load the selected language into the editor. Skipped while there are
  // unsaved edits so switching tabs and back does not silently discard them.
  useEffect(() => {
    if (!item || dirty) return;
    setArticleType(item.article_type);
    setDraft(toDraft(item.translations.find((t) => t.locale === locale)));
  }, [item, locale, dirty]);

  const update = (patch: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setDirty(true);
  };

  const types = assistant.data?.article_types ?? [];
  const canWrite = can("cms.content.write");
  const canPublish = can("cms.content.publish");

  const missingLocales = useMemo(() => {
    if (!item) return [];
    return locales.filter(
      (code) => !item.locales.some((l) => l.locale === code && l.is_complete),
    );
  }, [item, locales]);

  const body = pruneBlocks(draft.blocks);
  const saveError = (save.error ?? create.error ?? transition.error) as ApiError | null;

  const onSave = () => {
    if (isNew) {
      create.mutate(
        {
          club_id: clubId,
          article_type: articleType,
          cover_media_id: newCover?.id ?? null,
          translation: {
            locale,
            title: draft.title,
            body,
            excerpt: draft.excerpt || null,
          },
        },
        {
          onSuccess: (created) => {
            setDirty(false);
            toast.success(t("news", "created"), t("news", "createdHint"));
            navigate(path(`/news/${created.id}`), { replace: true });
          },
          onError: (error) => toast.error(t("site", "couldNotSave"), error.message),
        },
      );
      return;
    }
    save.mutate(
      {
        locale,
        title: draft.title,
        body,
        excerpt: draft.excerpt || null,
        // "Ready" means publishable in this language, which is exactly what a
        // title plus a body is.
        status: body.length > 0 && draft.title.trim() ? "READY" : "DRAFT",
      },
      {
        onSuccess: () => {
          setDirty(false);
          toast.success(t("news", "savedIn", { locale: locale.toUpperCase() }));
        },
        onError: (error) => toast.error(t("site", "couldNotSave"), error.message),
      },
    );
  };

  if (!isNew && query.error) {
    return (
      <ErrorState
        error={query.error}
        onRetry={() => void query.refetch()}
        title={t("common", "somethingWentWrong")}
        retryLabel={t("common", "tryAgain")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <button
        type="button"
        onClick={() => navigate(path("/news"))}
        className="inline-flex items-center gap-1 text-xs text-text-secondary transition-colors hover:text-text"
      >
        <ChevronLeft className="size-3.5" />
        {t("news", "title")}
      </button>

      <PageHeader
        eyebrow={
          <>
            <Newspaper className="size-3.5" />
            {ARTICLE_TYPE_LABELS[item?.article_type ?? articleType] ?? "Article"}
          </>
        }
        title={isNew ? t("news", "newArticle") : draft.title || t("news", "untitled")}
        description={
          isNew
            ? t("news", "whatKind")
            : undefined
        }
        meta={
          item ? (
            <Badge tone={STATUS_TONE[item.status]} dot size="md">
              {item.status.toLowerCase()}
            </Badge>
          ) : undefined
        }
        action={
          canWrite ? (
            <Button
              variant="primary"
              loading={save.isPending || create.isPending}
              disabled={!draft.title.trim()}
              onClick={onSave}
            >
              <Save />
              {t("common", "save")}
            </Button>
          ) : undefined
        }
      />

      {/* The server names the fields it refused; showing only `message` left
          "The submitted data is not valid." on screen with no way to find out
          which one. The field paths differ between saving a translation and
          creating an article — `excerpt` in one, `translation.excerpt` in the
          other — so both spellings map to the label actually on the field. */}
      {saveError && (
        <div className="text-sm text-danger" role="alert">
          <p>{saveError.message}</p>
          {Object.entries(saveError.fieldErrors).length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {Object.entries(saveError.fieldErrors).map(([field, message]) => {
                const labelKey = fieldLabelKey(field);
                return (
                  <li key={field}>
                    <span className="font-medium">
                      {labelKey ? t("news", labelKey) : field}
                    </span>
                    : {message}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-4">
          {isNew ? (
            <Card className="p-4">
              <p className="mb-3 text-sm font-medium text-text">{t("news", "whatKind")}</p>
              <TypePicker
                value={articleType}
                types={types}
                onChange={(type, skeleton) => {
                  setArticleType(type);
                  // The skeleton is a starting structure, so it only replaces an
                  // untouched body — never something already written.
                  if (draft.blocks.length === 0) update({ blocks: skeleton });
                }}
              />
            </Card>
          ) : (
null
          )}

          {/* Language tabs. Present even with one language, so adding a second
              later is a visible affordance rather than a hidden feature. */}
          <div className="flex flex-wrap items-center gap-1 border-b border-border">
            {locales.map((code) => {
              const state = item?.locales.find((l) => l.locale === code);
              return (
                <button
                  key={code}
                  type="button"
                  onClick={() => {
                    if (dirty && !window.confirm(t("news", "discardChanges"))) return;
                    setDirty(false);
                    setLocale(code);
                  }}
                  className={cn(
                    "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm",
                    code === locale
                      ? "border-brand text-text"
                      : "border-transparent text-text-secondary hover:text-text",
                  )}
                >
                  {code.toUpperCase()}
                  {state && !state.is_complete && (
                    <span
                      aria-label="incomplete"
                      className="size-1.5 rounded-full bg-warning"
                    />
                  )}
                </button>
              );
            })}
          </div>

          <Card className="space-y-4 p-4">
            <Field
              label={t("news", "articleTitle")}
              htmlFor="article-title"
              help={translation ? `/news/${translation.slug}` : undefined}
            >
              {(props) => (
                <Input
                  {...props}
                  value={draft.title}
                  disabled={!canWrite}
                  placeholder={t("news", "titlePlaceholder")}
                  className="text-base"
                  onChange={(event) => update({ title: event.target.value })}
                />
              )}
            </Field>

            {/* The limit is shown, and only once it is close enough to matter.
                It is the server's limit either way, and a summary pasted from
                the article body goes past it easily — being refused on save,
                after writing the whole piece, is the worst moment to find out
                and the error did not even say which field. */}
            <Field
              label={t("news", "summary")}
              htmlFor="article-excerpt"
              help={t("news", "summaryHint")}
            >
              {(props) => (
                <>
                  <Textarea
                    {...props}
                    rows={2}
                    value={draft.excerpt}
                    disabled={!canWrite}
                    maxLength={EXCERPT_MAX}
                    placeholder={t("news", "summaryPlaceholder")}
                    onChange={(event) => update({ excerpt: event.target.value })}
                  />
                  {draft.excerpt.length > EXCERPT_MAX * 0.75 && (
                    <p
                      className="mt-1 text-right text-xs text-text-tertiary"
                      data-numeric
                    >
                      {draft.excerpt.length} / {EXCERPT_MAX}
                    </p>
                  )}
                </>
              )}
            </Field>
          </Card>

          <BlockEditor
            blocks={draft.blocks}
            disabled={!canWrite}
            onChange={(blocks) => update({ blocks })}
          />
        </div>

        <div className="space-y-4">
          {/* The picture is chosen before the first save as well as after.
              It used to be deferred — the field was shown, explained and
              disabled until the article existed — on the reasoning that a new
              article has no id for an image to attach to. But the image does
              not attach to the article: it is uploaded to the club's media
              library, which exists already, and the article merely names it.
              So the id is held here and sent with the create. Writing a piece
              and picking its photograph is one job, and being told to come
              back for the second half of it is the kind of small refusal that
              gets a club posting to Facebook instead. */}
          {isNew && canWrite && (
            <Card className="p-4">
              <ImageField
                purpose="ARTICLE_IMAGE"
                label={t("news", "cover")}
                help={t("news", "coverHint")}
                value={newCover?.url ?? null}
                onChange={(asset) => {
                  setNewCover(asset);
                  // Otherwise choosing a picture and nothing else leaves the
                  // editor claiming there is nothing to save.
                  setDirty(true);
                }}
              />
            </Card>
          )}

          {item && canWrite && (
            <Card className="p-4">
              <ImageField
                purpose="ARTICLE_IMAGE"
                label={t("news", "cover")}
                help={t("news", "coverHint")}
                value={item.cover_url}
                onChange={(asset) =>
                  cover.mutate(
                    { id: item.id, changes: { cover_media_id: asset?.id ?? null } },
                    { onError: (error) => toast.error(error.message) },
                  )
                }
              />
            </Card>
          )}

          {assistant.data && canWrite && (
            <AssistantPanel
              status={assistant.data}
              contentItemId={isNew ? null : (itemId ?? null)}
              locale={locale}
              title={draft.title}
              blocks={draft.blocks}
              onApplyBlocks={(blocks) => update({ blocks })}
              onApplyTitle={(title) => update({ title })}
            />
          )}

          {item && canPublish && (
            <Card className="space-y-2.5 p-4">
              <p className="text-sm font-medium text-text">{t("news", "publishing")}</p>

              {missingLocales.length > 0 && (
                <p className="text-xs text-warning">
                  {t("news", "missingLocales", {
                    locales: missingLocales.join(", ").toUpperCase(),
                  })}
                </p>
              )}

              {NEXT_STATUS[item.status].map((target) => (
                <div key={target} className="space-y-1">
                  {target === "SCHEDULED" && (
                    <Input
                      type="datetime-local"
                      aria-label={t("news", "publishAt")}
                      leading={<Calendar />}
                      value={scheduledFor}
                      onChange={(event) => setScheduledFor(event.target.value)}
                    />
                  )}
                  <Button
                    variant={target === "PUBLISHED" ? "primary" : "secondary"}
                    size="sm"
                    className="w-full"
                    disabled={
                      dirty ||
                      transition.isPending ||
                      (target === "SCHEDULED" && !scheduledFor)
                    }
                    onClick={() =>
                      transition.mutate(
                        {
                          status: target,
                          scheduled_for:
                            target === "SCHEDULED"
                              ? new Date(scheduledFor).toISOString()
                              : null,
                        },
                        {
                          onSuccess: () => toast.success(t("news", ACTION_KEYS[target])),
                          onError: (error) =>
                            toast.error(t("site", "couldNotSave"), error.message),
                        },
                      )
                    }
                  >
                    {target === "PUBLISHED" && <Send />}
                    {t("news", ACTION_KEYS[target])}
                  </Button>
                </div>
              ))}

              {dirty && (
                <p className="text-xs text-text-tertiary">{t("news", "saveFirst")}</p>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
