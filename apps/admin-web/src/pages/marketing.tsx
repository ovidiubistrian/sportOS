import {
  useAudienceSize,
  useCampaigns,
  useCreateCampaign,
  useCreateEmailTemplate,
  useEmailPreview,
  useEmailTemplates,
  useSendCampaign,
  useUpdateEmailTemplate,
  type Block,
  type Campaign,
  type CampaignAudience,
  type EmailTemplate,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Section,
  Segmented,
  Select,
  Skeleton,
  useToast,
} from "@footbola/ui";
import { Mail, Send } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";
import { BlockEditor, emptyBlock, pruneBlocks } from "./news/blocks";

/**
 * Writing to the people who asked to hear from the club.
 *
 * Two halves that read in the order a club works in: the letters it writes,
 * and the sends it makes from them. A letter is reusable — "oferta de
 * echipament" goes out every August — which is why the two are separate at all.
 *
 * The audience count is deliberately loud. "You are about to write to 412
 * people" is the sentence that stops a mistake, and it is the number a club
 * most wants before it commits.
 */

const AUDIENCES: CampaignAudience[] = ["NEWSLETTER", "SUPPORTERS", "EVERYONE"];

function TemplateEditor({
  open,
  onOpenChange,
  template,
  clubId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  template: EmailTemplate | null;
  clubId: string;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const create = useCreateEmailTemplate();
  const update = useUpdateEmailTemplate();

  const [seeded, setSeeded] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [preheader, setPreheader] = useState("");
  const [ctaLabel, setCtaLabel] = useState("");
  const [ctaUrl, setCtaUrl] = useState("");
  const [blocks, setBlocks] = useState<Block[]>([emptyBlock("paragraph")]);

  const key = template?.id ?? (open ? "new" : null);
  if (key && seeded !== key) {
    setSeeded(key);
    setName(template?.name ?? "");
    setSubject(template?.subject ?? "");
    setPreheader(template?.preheader ?? "");
    setCtaLabel(template?.cta_label ?? "");
    setCtaUrl(template?.cta_url ?? "");
    setBlocks(template?.blocks?.length ? template.blocks : [emptyBlock("paragraph")]);
  }
  if (!open && seeded !== null) setSeeded(null);

  function submit() {
    const fields = {
      name: name.trim(),
      subject: subject.trim(),
      preheader: preheader.trim() || null,
      blocks: pruneBlocks(blocks),
      cta_label: ctaLabel.trim() || null,
      cta_url: ctaUrl.trim() || null,
    };
    const done = {
      onSuccess: () => {
        toast.success(t("marketing", "templateSaved"));
        onOpenChange(false);
      },
      onError: (error: Error) => toast.error(error.message),
    };

    if (template) update.mutate({ id: template.id, changes: fields }, done);
    else
      create.mutate(
        {
          club_id: clubId,
          // Derived from the name: a club should never be asked to invent a
          // machine-readable key for its own newsletter.
          key: `${name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40) || "letter"}-${Date.now().toString(36).slice(-4)}`,
          ...fields,
        },
        done,
      );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("marketing", template ? "editTemplate" : "newTemplate")}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            onClick={submit}
            loading={create.isPending || update.isPending}
            disabled={!name.trim() || subject.trim().length < 2}
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("marketing", "templateName")} required>
          {(props) => (
            <Input {...props} value={name} onChange={(e) => setName(e.target.value)} />
          )}
        </Field>

        <Field label={t("marketing", "subject")} help={t("marketing", "subjectHint")} required>
          {(props) => (
            <Input {...props} value={subject} onChange={(e) => setSubject(e.target.value)} />
          )}
        </Field>

        <Field label={t("marketing", "preheader")} help={t("marketing", "preheaderHint")}>
          {(props) => (
            <Input {...props} value={preheader} onChange={(e) => setPreheader(e.target.value)} />
          )}
        </Field>

        <div>
          <p className="mb-2 text-xs font-medium text-text">{t("marketing", "body")}</p>
          <BlockEditor blocks={blocks} onChange={setBlocks} />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("marketing", "ctaLabel")} help={t("marketing", "ctaHint")}>
            {(props) => (
              <Input {...props} value={ctaLabel} onChange={(e) => setCtaLabel(e.target.value)} />
            )}
          </Field>
          <Field label={t("marketing", "ctaUrl")}>
            {(props) => (
              <Input {...props} value={ctaUrl} onChange={(e) => setCtaUrl(e.target.value)} />
            )}
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

/** The letter exactly as it will arrive, in an isolated frame. */
function PreviewDialog({
  templateId,
  onClose,
}: {
  templateId: string | null;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const preview = useEmailPreview(templateId);

  return (
    <Dialog
      open={Boolean(templateId)}
      onOpenChange={(next) => !next && onClose()}
      title={preview.data?.subject ?? t("marketing", "preview")}
      size="lg"
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t("common", "close")}
        </Button>
      }
    >
      {preview.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        // An iframe with no scripts allowed: the email's own inline styles are
        // the point of the preview, and they must not leak into the admin.
        <iframe
          title={t("marketing", "preview")}
          sandbox=""
          srcDoc={preview.data?.html ?? ""}
          className="h-[28rem] w-full rounded-lg border border-border bg-white"
        />
      )}
    </Dialog>
  );
}

function CampaignRow({ campaign, onSend }: { campaign: Campaign; onSend: () => void }) {
  const { t } = useI18n();
  const done = campaign.status === "SENT";

  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-3">
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-text">{campaign.name}</span>
        <span className="block text-xs text-text-secondary">
          {t("marketing", `audience${campaign.audience}` as "audienceNEWSLETTER")}
          {done && ` · ${campaign.sent}/${campaign.total}`}
          {campaign.failed > 0 && ` · ${campaign.failed} ${t("marketing", "failed")}`}
        </span>
      </span>
      <Badge tone={done ? "success" : campaign.status === "FAILED" ? "danger" : "neutral"}>
        {t("marketing", `status${campaign.status}` as "statusDRAFT")}
      </Badge>
      {!done && campaign.status !== "SENDING" && (
        <Button variant="secondary" onClick={onSend}>
          <Send className="mr-1.5 size-3.5" />
          {t("marketing", "send")}
        </Button>
      )}
    </li>
  );
}

export function MarketingPage() {
  const { t, formatNumber } = useI18n();
  const { club, can } = useSession();
  const toast = useToast();

  const templates = useEmailTemplates(club?.id);
  const campaigns = useCampaigns(club?.id);
  const send = useSendCampaign();
  const createCampaign = useCreateCampaign();

  const [editing, setEditing] = useState<EmailTemplate | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [previewing, setPreviewing] = useState<string | null>(null);

  const [campaignName, setCampaignName] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [audience, setAudience] = useState<CampaignAudience>("NEWSLETTER");
  const reach = useAudienceSize(club?.id, audience);

  const canWrite = can("cms.content.publish");

  function planAndSend() {
    if (!club || !templateId) return;
    createCampaign.mutate(
      {
        club_id: club.id,
        template_id: templateId,
        name: campaignName.trim() || t("marketing", "untitled"),
        audience,
      },
      {
        onSuccess: (campaign) => {
          setCampaignName("");
          send.mutate(campaign.id, {
            onSuccess: (result) =>
              toast.success(
                t("marketing", "sentTo", { count: String(result.sent) }),
              ),
            onError: (error) => toast.error(error.message),
          });
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("marketing", "eyebrow")}
        title={t("marketing", "title")}
        description={t("marketing", "description")}
        action={
          canWrite && (
            <Button
              onClick={() => {
                setEditing(null);
                setEditorOpen(true);
              }}
            >
              {t("marketing", "newTemplate")}
            </Button>
          )
        }
      />

      <Section title={t("marketing", "newCampaign")} description={t("marketing", "newCampaignHint")}>
        <Card className="space-y-4 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("marketing", "campaignName")}>
              {(props) => (
                <Input
                  {...props}
                  value={campaignName}
                  onChange={(e) => setCampaignName(e.target.value)}
                  placeholder={t("marketing", "campaignNamePlaceholder")}
                />
              )}
            </Field>
            <Field label={t("marketing", "template")}>
              {(props) => (
                <Select
                  {...props}
                  value={templateId}
                  onChange={setTemplateId}
                  placeholder={t("marketing", "chooseTemplate")}
                  options={(templates.data ?? []).map((row) => ({
                    value: row.id,
                    label: row.name,
                  }))}
                />
              )}
            </Field>
          </div>

          <div>
            <p className="mb-1.5 text-xs font-medium text-text">{t("marketing", "audience")}</p>
            <Segmented
              ariaLabel={t("marketing", "audience")}
              value={audience}
              onChange={(next) => setAudience(next as CampaignAudience)}
              options={AUDIENCES.map((pool) => ({
                value: pool,
                label: t("marketing", `audience${pool}` as "audienceNEWSLETTER"),
              }))}
            />
            {/* The number that stops a mistake. */}
            <p className="mt-2 text-sm text-text-secondary">
              {reach.data ? (
                <>
                  <span className="font-medium text-text">
                    {formatNumber(reach.data.total)}
                  </span>{" "}
                  {t("marketing", "peopleConsented")} · {reach.data.provider}
                </>
              ) : (
                t("common", "loading")
              )}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              onClick={planAndSend}
              loading={createCampaign.isPending || send.isPending}
              disabled={!canWrite || !templateId || (reach.data?.total ?? 0) === 0}
            >
              <Send className="mr-1.5 size-3.5" />
              {t("marketing", "sendNow")}
            </Button>
            {templateId && (
              <Button variant="ghost" onClick={() => setPreviewing(templateId)}>
                {t("marketing", "preview")}
              </Button>
            )}
          </div>
        </Card>
      </Section>

      <Section title={t("marketing", "templates")} description={t("marketing", "templatesHint")}>
        {templates.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (templates.data?.length ?? 0) === 0 ? (
          <EmptyState
            icon={<Mail className="size-5" />}
            title={t("marketing", "noTemplates")}
            description={t("marketing", "noTemplatesBody")}
          />
        ) : (
          <Card>
            <ul className="divide-y divide-border">
              {(templates.data ?? []).map((row) => (
                <li key={row.id} className="flex items-center gap-3 px-3 py-3">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-text">
                      {row.name}
                    </span>
                    <span className="block truncate text-xs text-text-secondary">
                      {row.subject}
                    </span>
                  </span>
                  <Button variant="ghost" onClick={() => setPreviewing(row.id)}>
                    {t("marketing", "preview")}
                  </Button>
                  {canWrite && (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setEditing(row);
                        setEditorOpen(true);
                      }}
                    >
                      {t("common", "edit")}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </Section>

      <Section title={t("marketing", "history")} description={t("marketing", "historyHint")}>
        {(campaigns.data?.length ?? 0) === 0 ? (
          <p className="text-xs text-text-secondary">{t("marketing", "noCampaigns")}</p>
        ) : (
          <Card>
            <ul className="divide-y divide-border">
              {(campaigns.data ?? []).map((campaign) => (
                <CampaignRow
                  key={campaign.id}
                  campaign={campaign}
                  onSend={() =>
                    send.mutate(campaign.id, {
                      onSuccess: (result) =>
                        toast.success(
                          t("marketing", "sentTo", { count: String(result.sent) }),
                        ),
                      onError: (error) => toast.error(error.message),
                    })
                  }
                />
              ))}
            </ul>
          </Card>
        )}
      </Section>

      {club && (
        <TemplateEditor
          open={editorOpen}
          onOpenChange={setEditorOpen}
          template={editing}
          clubId={club.id}
        />
      )}
      <PreviewDialog templateId={previewing} onClose={() => setPreviewing(null)} />

      <p className="text-xs text-text-tertiary">{t("marketing", "consentNote")}</p>
    </div>
  );
}
