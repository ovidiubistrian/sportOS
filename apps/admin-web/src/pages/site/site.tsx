import {
  useBranding,
  useUpdateBranding,
  type Branding,
  type ColorMode,
  type SiteTemplate,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Section,
  Segmented,
  Skeleton,
  Textarea,
  Tooltip,
  cn,
  useToast,
} from "@footbola/ui";
import {
  Check,
  ExternalLink,
  Eye,
  Globe,
  Info,
  Monitor,
  RotateCcw,
  Smartphone,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";
import { ImageField } from "./image-field";
import { TemplateThumbnail, resolvedPalette } from "./template-preview";
import { clubHostname, clubSiteUrl } from "../../app/site-url";

/**
 * Site & design.
 *
 * A club picks a template and up to three colours. That is the whole surface —
 * no custom CSS, no per-component overrides. The constraint is deliberate: it
 * is what keeps every club site recognisably the same product, and what stops
 * a brand colour making a club's own site unreadable.
 *
 * Contrast is checked server-side and reported per colour, so the advice a club
 * sees is the same maths the public site actually renders with.
 */

const TEMPLATE_COPY: Record<SiteTemplate, { name: string; description: string }> = {
  CLASSIC: {
    name: "Classic",
    description: "Centred crest, formal masthead, squads as tables. Works with no photography.",
  },
  BOLD: {
    name: "Bold",
    description: "Full-bleed colour hero and very large type. For a strong visual identity.",
  },
  COMPACT: {
    name: "Compact",
    description: "Information first: narrow, dense, no hero. Built for busy academies.",
  },
  EDITORIAL: {
    name: "Editorial",
    description: "Magazine layout, generous whitespace. For clubs that publish often.",
  },
};

const COLOR_FIELDS = [
  {
    key: "color_primary" as const,
    check: "primary",
    labelKey: "primary",
    helpKey: "primaryHint",
    required: true,
  },
  {
    key: "color_secondary" as const,
    check: "secondary",
    labelKey: "secondary",
    helpKey: "secondaryHint",
    required: false,
  },
  {
    key: "color_accent" as const,
    check: "accent",
    labelKey: "accent",
    helpKey: "accentHint",
    required: false,
  },
] as const;

/** A few starting points, so a club is not staring at a colour wheel. */
const PRESETS: { name: string; primary: string; secondary: string }[] = [
  { name: "Royal", primary: "#1F4B99", secondary: "#F2B705" },
  { name: "Forest", primary: "#0F5132", secondary: "#E8E5D8" },
  { name: "Claret", primary: "#7A1F35", secondary: "#8FB8DE" },
  { name: "Midnight", primary: "#131A2B", secondary: "#D64545" },
  { name: "Sky", primary: "#0B6BA8", secondary: "#F5F7FA" },
  { name: "Amber", primary: "#B45309", secondary: "#1F2937" },
];

const EDITABLE_KEYS = [
  "template",
  "color_mode",
  "color_primary",
  "color_secondary",
  "color_accent",
  "tagline",
  "display_name",
  "short_name",
  "crest_media_id",
  "hero_media_id",
  "contact_email",
  "contact_phone",
  "address",
  "legal_line",
  "sponsors_title",
] as const;

function Swatch({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        aria-hidden
        className="size-5 rounded-md border border-border shadow-xs"
        style={{ background: value }}
      />
      <span className="text-xs text-text-secondary">
        {label}
        <code className="ml-1 font-mono text-[0.625rem] text-text-tertiary">{value}</code>
      </span>
    </div>
  );
}

function ColorRow({
  label,
  help,
  value,
  check,
  required,
  disabled,
  onChange,
  contrastLabel,
  textUsesLabel,
}: {
  label: string;
  help: string;
  value: string | null;
  check: Branding["checks"][string] | undefined;
  required: boolean;
  disabled: boolean;
  onChange: (next: string | null) => void;
  contrastLabel: (ratio: string) => string;
  textUsesLabel: string;
}) {
  const current = value ?? "";
  const id = `color-${label.toLowerCase()}`;

  return (
    <div className="border-b border-border-subtle py-4 last:border-0">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <label className="text-sm font-medium text-text" htmlFor={id}>
            {label}
          </label>
          <p className="mt-0.5 text-xs text-text-secondary">{help}</p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <label
            className={cn(
              "relative size-8 shrink-0 overflow-hidden rounded-md border border-border shadow-xs",
              disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
            )}
            style={{ background: current || "#1F4B99" }}
          >
            <input
              id={id}
              type="color"
              value={current || "#1F4B99"}
              disabled={disabled}
              onChange={(event) => onChange(event.target.value.toUpperCase())}
              className="absolute inset-0 cursor-pointer opacity-0"
              aria-label={`${label} colour`}
            />
          </label>
          <Input
            value={current}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value.toUpperCase() || null)}
            placeholder="#1F4B99"
            className="w-28 font-mono"
            aria-label={`${label} hex value`}
          />
          {!required && value && !disabled && (
            <Button variant="ghost" size="sm" onClick={() => onChange(null)}>
              Clear
            </Button>
          )}
        </div>
      </div>

      {check && (
        <div className="mt-2.5 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={check.meets_aa_as_text ? "success" : "warning"} dot>
              {contrastLabel(check.contrast_on_white.toFixed(1))}
            </Badge>
            {check.was_adjusted && (
              <span className="flex items-center gap-1 text-xs text-text-secondary">
                {textUsesLabel}
                <span
                  aria-hidden
                  className="inline-block size-3 rounded-[3px] border border-border"
                  style={{ background: check.text_variant }}
                />
                <code className="font-mono">{check.text_variant}</code>
              </span>
            )}
          </div>
          {check.advice && (
            <p className="text-xs leading-relaxed text-text-secondary">{check.advice}</p>
          )}
        </div>
      )}
    </div>
  );
}

function LivePreview({ url }: { url: string }) {
  const { t } = useI18n();
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [nonce, setNonce] = useState(0);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-border bg-bg-subtle px-3 py-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-text-secondary">
          <Eye className="size-3.5" />
          {t("site", "livePreview")}
        </span>
        <div className="flex items-center gap-1.5">
          <Segmented
            ariaLabel={t("site", "previewDevice")}
            size="sm"
            value={device}
            onChange={setDevice}
            options={[
              {
                value: "desktop",
                label: <Monitor className="size-3.5" />,
                title: t("site", "desktop"),
              },
              {
                value: "mobile",
                label: <Smartphone className="size-3.5" />,
                title: t("site", "mobile"),
              },
            ]}
          />
          <Tooltip content={t("site", "reloadPreview")}>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("site", "reloadPreview")}
              onClick={() => setNonce((n) => n + 1)}
            >
              <RotateCcw />
            </Button>
          </Tooltip>
          <Tooltip content={t("site", "openInNewTab")}>
            <Button variant="ghost" size="icon-sm" asChild>
              <a href={url} target="_blank" rel="noreferrer" aria-label={t("site", "openInNewTab")}>
                <ExternalLink />
              </a>
            </Button>
          </Tooltip>
        </div>
      </div>

      <div className="grid place-items-center bg-bg-muted p-4">
        <div
          className={cn(
            "overflow-hidden rounded-lg border border-border bg-white shadow-lg transition-[width] duration-[--duration-base]",
            device === "mobile" ? "w-[22rem]" : "w-full",
          )}
        >
          {/* The real site in an iframe. A scale model is enough to *choose* a
              template; only the real thing settles "does my club's site look
              right". Saved changes appear on the next reload, because the
              public site is cached and purged by the branding event. */}
          <iframe
            key={`${url}-${nonce}-${device}`}
            src={url}
            title="Club website preview"
            className="h-[34rem] w-full border-0 bg-white"
            sandbox="allow-same-origin allow-scripts"
          />
        </div>
      </div>
    </Card>
  );
}

export function SitePage() {
  const { can, club } = useSession();
  const { t } = useI18n();
  const toast = useToast();
  const clubId = club.id;

  const query = useBranding(clubId);
  const mutation = useUpdateBranding(clubId);
  const [draft, setDraft] = useState<Branding | null>(null);
  const editable = can("clubs.club.update");

  // The server's response is the source of truth for the derived palette, so
  // the draft resets whenever a save comes back.
  useEffect(() => {
    if (query.data) setDraft(query.data);
  }, [query.data]);

  const dirty = useMemo(
    () =>
      Boolean(draft && query.data) &&
      EDITABLE_KEYS.some((key) => draft![key] !== query.data![key]),
    [draft, query.data],
  );

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

  if (!draft) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-56" />
        <div className="grid gap-6 xl:grid-cols-[minmax(0,28rem)_minmax(0,1fr)]">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      </div>
    );
  }

  const update = <K extends keyof Branding>(key: K, value: Branding[K]) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));

  const save = () =>
    mutation.mutate(
      {
        template: draft.template,
        color_mode: draft.color_mode,
        color_primary: draft.color_primary,
        color_secondary: draft.color_secondary,
        color_accent: draft.color_accent,
        tagline: draft.tagline,
        display_name: draft.display_name ?? undefined,
        short_name: draft.short_name ?? undefined,
        crest_media_id: draft.crest_media_id,
        hero_media_id: draft.hero_media_id,
      },
      {
        onSuccess: () =>
          toast.success(t("site", "saved"), t("site", "savedHint")),
        onError: (error) => toast.error(t("site", "couldNotSave"), error.message),
      },
    );

  const palette = resolvedPalette(draft);
  const siteUrl = clubSiteUrl(club.slug);

  return (
    <div className="space-y-8 pb-20">
      <PageHeader
        eyebrow={
          <>
            <Globe className="size-3.5" />
            {clubHostname(club.slug)}
          </>
        }
        title={t("site", "title")}
        description={t("site", "description", { club: club.display_name })}
        meta={<Badge tone="brand">{draft.template.toLowerCase()}</Badge>}
      />

      <div className="grid gap-8 xl:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
        <div className="space-y-8">
          <Section
            title={t("site", "template")}
            description={t("site", "templateHint")}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {draft.available_templates.map((name) => {
                const copy = TEMPLATE_COPY[name];
                const selected = draft.template === name;
                return (
                  <button
                    key={name}
                    type="button"
                    disabled={!editable}
                    aria-pressed={selected}
                    onClick={() => update("template", name)}
                    className={cn(
                      "group overflow-hidden rounded-lg border text-left transition-all duration-[--duration-fast]",
                      "disabled:cursor-not-allowed disabled:opacity-60",
                      selected
                        ? "border-brand shadow-md ring-1 ring-brand"
                        : "border-border hover:-translate-y-px hover:border-border-strong hover:shadow-md",
                    )}
                  >
                    <div className="relative h-32 overflow-hidden bg-bg-muted">
                      <div className="pointer-events-none origin-top scale-[0.62]">
                        <TemplateThumbnail
                          branding={{ ...draft, template: name }}
                          clubName={club.display_name}
                          shortName={club.short_name}
                        />
                      </div>
                      {selected && (
                        <span
                          aria-hidden
                          className="absolute top-2 right-2 grid size-5 place-items-center rounded-full bg-brand text-brand-contrast shadow-sm"
                        >
                          <Check className="size-3" />
                        </span>
                      )}
                    </div>
                    <div className="border-t border-border bg-surface p-3">
                      <span className="block text-sm font-medium text-text">{copy.name}</span>
                      <span className="mt-0.5 block text-xs leading-relaxed text-text-secondary">
                        {copy.description}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </Section>

          <Section
            title={t("site", "colours")}
            description={t("site", "coloursHint")}
          >
            <Card className="px-4">
              {COLOR_FIELDS.map((field) => (
                <ColorRow
                  key={field.key}
                  label={t("site", field.labelKey)}
                  help={t("site", field.helpKey)}
                  required={field.required}
                  disabled={!editable}
                  value={draft[field.key]}
                  check={draft.checks[field.check]}
                  contrastLabel={(ratio) => t("site", "contrastOnWhite", { ratio })}
                  textUsesLabel={t("site", "textUses")}
                  onChange={(next) =>
                    update(field.key, (field.required ? (next ?? "#1F4B99") : next) as never)
                  }
                />
              ))}
            </Card>

            <div className="flex flex-wrap items-center gap-2">
              <span className="flex items-center gap-1 text-xs text-text-tertiary">
                <Sparkles className="size-3.5" />
                {t("site", "startFrom")}
              </span>
              {PRESETS.map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  disabled={!editable}
                  onClick={() => {
                    update("color_primary", preset.primary);
                    update("color_secondary", preset.secondary);
                  }}
                  className="flex items-center gap-1.5 rounded-full border border-border bg-surface py-1 pr-2.5 pl-1 text-xs text-text-secondary transition-colors hover:border-border-strong hover:text-text disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <span className="flex">
                    <span
                      aria-hidden
                      className="size-4 rounded-full border border-white/60"
                      style={{ background: preset.primary }}
                    />
                    <span
                      aria-hidden
                      className="-ml-1.5 size-4 rounded-full border border-white/60"
                      style={{ background: preset.secondary }}
                    />
                  </span>
                  {preset.name}
                </button>
              ))}
            </div>

            <Card className="p-3">
              <p className="mb-2 flex items-center gap-1 text-xs text-text-secondary">
                <Info className="size-3.5" />
                {t("site", "resolvedPalette")}
              </p>
              <div className="flex flex-wrap gap-3">
                <Swatch label="Brand" value={palette.brand} />
                <Swatch label="On brand" value={palette.onBrand} />
                <Swatch label="Brand text" value={palette.brandText} />
                {palette.secondary && (
                  <Swatch label="Secondary" value={palette.secondary} />
                )}
              </div>
            </Card>
          </Section>

          <Section title="Images" description="The crest and the picture at the top of the home page.">
            <Card className="space-y-6 p-4">
              <ImageField
                purpose="CREST"
                label="Club crest"
                help="Shown in the site header, the admin and link previews. A square PNG with a transparent background works best."
                aspect="1/1"
                value={draft.crest_url}
                onChange={(asset) =>
                  setDraft((current) =>
                    current
                      ? {
                          ...current,
                          crest_media_id: asset?.id ?? null,
                          crest_url: asset?.url ?? null,
                        }
                      : current,
                  )
                }
              />
              <ImageField
                purpose="HERO"
                label="Home page image"
                help="The wide picture behind the club name. A photograph from a matchday reads better than a graphic."
                aspect="16/7"
                value={draft.hero_url}
                onChange={(asset) =>
                  setDraft((current) =>
                    current
                      ? {
                          ...current,
                          hero_media_id: asset?.id ?? null,
                          hero_url: asset?.url ?? null,
                        }
                      : current,
                  )
                }
              />
            </Card>
          </Section>

          <Section title={t("site", "footer")} description={t("site", "footerHint")}>
            <Card className="space-y-4 p-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t("site", "footerEmail")}>
                  {(props) => (
                    <Input
                      {...props}
                      type="email"
                      value={draft.contact_email ?? ""}
                      maxLength={320}
                      disabled={!editable}
                      placeholder="contact@club.ro"
                      onChange={(event) =>
                        update("contact_email", event.target.value || null)
                      }
                    />
                  )}
                </Field>
                <Field label={t("site", "footerPhone")}>
                  {(props) => (
                    <Input
                      {...props}
                      type="tel"
                      value={draft.contact_phone ?? ""}
                      maxLength={32}
                      disabled={!editable}
                      placeholder="+40 255 210 000"
                      onChange={(event) =>
                        update("contact_phone", event.target.value || null)
                      }
                    />
                  )}
                </Field>
              </div>

              <Field label={t("site", "footerAddress")} help={t("site", "footerAddressHint")}>
                {(props) => (
                  <Textarea
                    {...props}
                    rows={3}
                    value={draft.address ?? ""}
                    maxLength={400}
                    disabled={!editable}
                    onChange={(event) => update("address", event.target.value || null)}
                  />
                )}
              </Field>

              <Field label={t("site", "footerLegal")} help={t("site", "footerLegalHint")}>
                {(props) => (
                  <Input
                    {...props}
                    value={draft.legal_line ?? ""}
                    maxLength={300}
                    disabled={!editable}
                    placeholder="CIF 12345678 · Reg. Com. J11/123/1990"
                    onChange={(event) => update("legal_line", event.target.value || null)}
                  />
                )}
              </Field>

              <Field label={t("site", "footerSponsorsTitle")} help={t("site", "footerSponsorsHint")}>
                {(props) => (
                  <Input
                    {...props}
                    value={draft.sponsors_title ?? ""}
                    maxLength={80}
                    disabled={!editable}
                    placeholder={t("site", "footerSponsorsPlaceholder")}
                    onChange={(event) =>
                      update("sponsors_title", event.target.value || null)
                    }
                  />
                )}
              </Field>
            </Card>
          </Section>

          <Section title={t("site", "identity")} description={t("site", "identityHint")}>
            <Card className="space-y-4 p-4">
              <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
                <Field label={t("site", "clubName")} help={t("site", "clubNameHint")}>
                  {(props) => (
                    <Input
                      {...props}
                      value={draft.display_name ?? ""}
                      maxLength={160}
                      disabled={!editable}
                      onChange={(event) =>
                        update("display_name", event.target.value || null)
                      }
                    />
                  )}
                </Field>

                <Field label={t("site", "wordmark")} help={t("site", "wordmarkHint")}>
                  {(props) => (
                    <Input
                      {...props}
                      value={draft.short_name ?? ""}
                      maxLength={8}
                      disabled={!editable}
                      placeholder="CSM"
                      onChange={(event) =>
                        update("short_name", event.target.value || null)
                      }
                    />
                  )}
                </Field>
              </div>

              <Field
                label={t("site", "tagline")}
                help={t("site", "taglineHint")}
              >
                {(props) => (
                  <Input
                    {...props}
                    value={draft.tagline ?? ""}
                    maxLength={160}
                    disabled={!editable}
                    placeholder="Since 1921, for the city."
                    onChange={(event) => update("tagline", event.target.value || null)}
                  />
                )}
              </Field>

              <fieldset>
                <legend className="mb-1.5 text-xs font-medium text-text">
                  {t("site", "colourMode")}
                </legend>
                <Segmented
                  ariaLabel={t("site", "colourMode")}
                  value={draft.color_mode}
                  onChange={(mode) => editable && update("color_mode", mode as ColorMode)}
                  options={draft.available_color_modes.map((mode) => ({
                    value: mode,
                    label: mode.toLowerCase(),
                  }))}
                />
                <p className="mt-1.5 text-xs text-text-tertiary">
                  {t("site", "colourModeHint")}
                </p>
              </fieldset>
            </Card>
          </Section>
        </div>

        <div className="xl:sticky xl:top-20 xl:self-start">
          {siteUrl && <LivePreview url={siteUrl} />}
        </div>
      </div>

      {/* A save bar rather than a button in the header: on a long settings page
          the action must stay reachable from wherever the change was made. */}
      {editable && dirty && (
        <div className="animate-slide-up fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface/90 backdrop-blur-md">
          <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-4 px-5 py-3 lg:px-8">
            <p className="text-sm text-text-secondary">{t("site", "unsavedDesign")}</p>
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => setDraft(query.data ?? null)}>
                {t("common", "discard")}
              </Button>
              <Button variant="primary" loading={mutation.isPending} onClick={save}>
                {t("site", "saveChanges")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
