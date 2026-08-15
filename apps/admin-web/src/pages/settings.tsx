import { useAssistant } from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  DescriptionList,
  PageHeader,
  Progress,
  Section,
  cn,
} from "@footbola/ui";
import { Building2, Check, Languages, Sparkles, X } from "lucide-react";

import { LOCALES } from "@footbola/i18n";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";

/**
 * Settings.
 *
 * Read-only for now, and honest about it. What a tenant *is* — its languages,
 * currency, timezone and what its plan includes — is worth showing even before
 * it is editable, because it is the answer to "why can't I do X?" and every
 * support conversation starts there.
 */

function PermissionList({ permissions }: { permissions: string[] }) {
  const byModule = permissions.reduce<Record<string, string[]>>((acc, permission) => {
    const [module = "other"] = permission.split(".");
    (acc[module] ??= []).push(permission);
    return acc;
  }, {});

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Object.entries(byModule)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([module, keys]) => (
          <Card key={module} className="p-3">
            <p className="text-xs font-medium tracking-wide text-text-tertiary uppercase">
              {module}
            </p>
            <ul className="mt-2 space-y-1">
              {keys.sort().map((key) => (
                <li key={key} className="flex items-start gap-1.5 text-xs text-text-secondary">
                  <Check className="mt-0.5 size-3 shrink-0 text-success" />
                  <span className="font-mono">{key.split(".").slice(1).join(".")}</span>
                </li>
              ))}
            </ul>
          </Card>
        ))}
    </div>
  );
}

export function SettingsPage() {
  const { me, club } = useSession();
  const { t, locale, tenantLocale, override, setOverride } = useI18n();
  const assistant = useAssistant();
  const tenant = me.active_tenant;

  const used = assistant.data?.requests_used ?? 0;
  const limit = assistant.data?.requests_limit ?? null;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={
          <>
            <Building2 className="size-3.5" />
            {t("settings", "eyebrow")}
          </>
        }
        title={t("settings", "title")}
        description={t("settings", "description")}
        meta={
          tenant?.is_demo ? (
            <Badge tone="warning" dot>
              {t("settings", "demoData")}
            </Badge>
          ) : undefined
        }
      />

      <Section title={t("settings", "tenant")} description={t("settings", "tenantHint")}>
        <Card className="p-5">
          <DescriptionList
            columns={3}
            items={[
              { term: t("settings", "legalName"), value: tenant?.legal_name ?? "—" },
              { term: t("settings", "tradingName"), value: tenant?.trading_name ?? "—" },
              {
                term: t("settings", "slug"),
                value: <code className="font-mono">{tenant?.slug}</code>,
              },
              {
                term: t("settings", "status"),
                value: (
                  <Badge tone={tenant?.status === "ACTIVE" ? "success" : "warning"} dot>
                    {tenant?.status.toLowerCase()}
                  </Badge>
                ),
              },
              { term: t("settings", "currency"), value: tenant?.default_currency ?? "—" },
              { term: t("settings", "timezone"), value: tenant?.timezone ?? "—" },
            ]}
          />
        </Card>
      </Section>

      <Section
        title={t("settings", "languages")}
        description={t("settings", "languagesHint")}
      >
        <Card className="flex flex-wrap items-center gap-2 p-4">
          <Languages className="size-4 text-text-tertiary" />
          {(tenant?.supported_locales ?? []).map((code) => (
            <Badge
              key={code}
              tone={code === tenant?.default_locale ? "brand" : "outline"}
              size="md"
            >
              {code.toUpperCase()}
              {code === tenant?.default_locale && ` · ${t("settings", "default")}`}
            </Badge>
          ))}
        </Card>
      </Section>

      <Section
        title={t("settings", "interfaceLanguage")}
        description={t("settings", "interfaceLanguageHint")}
      >
        <Card className="flex flex-wrap items-center gap-2 p-4">
          <Languages className="size-4 text-text-tertiary" />
          {LOCALES.map((option) => (
            <Button
              key={option.code}
              size="sm"
              variant={option.code === locale ? "primary" : "secondary"}
              onClick={() => setOverride(option.code)}
            >
              {option.endonym}
            </Button>
          ))}
          {override && override !== tenantLocale && (
            <Button variant="ghost" size="sm" onClick={() => setOverride(null)}>
              {tenantLocale.toUpperCase()} · {t("settings", "default")}
            </Button>
          )}
        </Card>
      </Section>

      <Section
        title={t("settings", "assistant")}
        description={t("settings", "assistantHint")}
      >
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <span
                aria-hidden
                className={cn(
                  "grid size-9 shrink-0 place-items-center rounded-lg",
                  assistant.data?.available
                    ? "bg-success-bg text-success"
                    : "bg-bg-muted text-text-tertiary",
                )}
              >
                {assistant.data?.available ? (
                  <Sparkles className="size-4" />
                ) : (
                  <X className="size-4" />
                )}
              </span>
              <div>
                <p className="text-sm font-medium text-text">
                  {t("settings", assistant.data?.available ? "available" : "notAvailable")}
                </p>
                <p className="mt-0.5 max-w-md text-sm text-text-secondary">
                  {assistant.data?.reason ?? t("settings", "assistantBody")}
                </p>
              </div>
            </div>

            {limit != null && (
              <div className="w-48">
                <p className="mb-1.5 flex justify-between text-xs text-text-secondary">
                  <span>{t("settings", "thisMonth")}</span>
                  <span data-numeric>
                    {used} / {limit}
                  </span>
                </p>
                <Progress
                  value={used}
                  max={limit}
                  label="Assistant requests used this month"
                  tone={used / Math.max(limit, 1) > 0.85 ? "warning" : "brand"}
                />
              </div>
            )}
          </div>
        </Card>
      </Section>

      <Section
        title={t("settings", "yourAccess")}
        description={t("settings", "yourAccessHint", {
          email: me.email,
          club: club.display_name,
        })}
      >
        <PermissionList permissions={me.permissions} />
      </Section>
    </div>
  );
}
