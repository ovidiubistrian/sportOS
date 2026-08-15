import {
  usePlatformCompetitions,
  usePlatformPlans,
  usePlatformTenants,
  useSaveCompetition,
  useSetTenantPlan,
  type PlatformCompetition,
  type PlatformTenant,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Section,
  Select,
  Skeleton,
  Switch,
  cn,
  useToast,
} from "@footbola/ui";
import { Building2, Search } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../app/locale";

/**
 * The super-admin console.
 *
 * Two things, because they are the two that cannot be done from inside a
 * tenant: who is on the platform and what they are paying for, and the
 * competition catalogue every tenant reads.
 *
 * Impersonation is deliberately not a button here. It requires a second factor
 * and writes an audited grant, so it belongs on a tenant's own row with a
 * reason field — and until this console has that, "open the tenant" is a thing
 * an operator does knowingly rather than by misclicking a table.
 */

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  ACTIVE: "success",
  PENDING: "warning",
  SUSPENDED: "danger",
  CLOSED: "neutral",
};

function TenantRow({
  tenant,
  plans,
  onPlan,
}: {
  tenant: PlatformTenant;
  plans: string[];
  onPlan: (plan: string) => void;
}) {
  const { formatNumber, formatDate } = useI18n();

  return (
    <li className="grid items-center gap-3 border-b border-border py-3 last:border-0 sm:grid-cols-[1fr_auto_10rem_auto]">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-text">{tenant.name}</p>
        <p className="mt-0.5 truncate text-xs text-text-tertiary">
          {tenant.slug} · {tenant.country_code} · {tenant.default_currency} ·{" "}
          {tenant.supported_locales.join(", ")}
        </p>
      </div>

      <p className="text-xs tabular-nums text-text-secondary">
        {formatNumber(tenant.clubs)} / {formatNumber(tenant.players)}
      </p>

      <Select
        value={tenant.plan ?? ""}
        onChange={onPlan}
        size="sm"
        ariaLabel="Plan"
        options={plans.map((key) => ({ value: key, label: key }))}
      />

      <div className="flex items-center gap-2 sm:justify-end">
        {tenant.subscription_status === "TRIALING" && tenant.trial_ends_at && (
          <span className="hidden text-xs text-text-tertiary lg:inline">
            trial → {formatDate(tenant.trial_ends_at)}
          </span>
        )}
        <Badge tone={STATUS_TONE[tenant.status] ?? "neutral"} dot>
          {tenant.status.toLowerCase()}
        </Badge>
      </div>
    </li>
  );
}

/* --- competitions ----------------------------------------------------------- */

const FORMATS = ["LEAGUE", "KNOCKOUT", "GROUP_KNOCKOUT"] as const;
const SCOPES = ["DOMESTIC_LEAGUE", "DOMESTIC_CUP", "CONTINENTAL"] as const;

function CompetitionEditor({
  open,
  onOpenChange,
  competition,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  competition: PlatformCompetition | null;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const save = useSaveCompetition();

  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [shortName, setShortName] = useState("");
  const [country, setCountry] = useState("RO");
  const [format, setFormat] = useState<(typeof FORMATS)[number]>("LEAGUE");
  const [scope, setScope] = useState<(typeof SCOPES)[number]>("DOMESTIC_LEAGUE");
  const [tier, setTier] = useState("");
  const [sortOrder, setSortOrder] = useState("0");
  const [isActive, setIsActive] = useState(true);
  const [seeded, setSeeded] = useState<string | null>(null);

  const seedKey = competition?.id ?? (open ? "new" : null);
  if (seedKey && seeded !== seedKey) {
    setSeeded(seedKey);
    setName(competition?.name ?? "");
    setKey(competition?.key ?? "");
    setShortName(competition?.short_name ?? "");
    setCountry(competition?.country_code ?? "RO");
    setFormat(competition?.format ?? "LEAGUE");
    setScope((competition?.scope as (typeof SCOPES)[number]) ?? "DOMESTIC_LEAGUE");
    setTier(competition?.tier?.toString() ?? "");
    setSortOrder(competition?.sort_order?.toString() ?? "0");
    setIsActive(competition?.is_active ?? true);
  }
  if (!open && seeded !== null) setSeeded(null);

  // The database enforces this pairing; saying so here turns a 500 into a
  // sentence: only a domestic league sits in the pyramid, so only it has a tier.
  const needsTier = scope === "DOMESTIC_LEAGUE";
  const continental = scope === "CONTINENTAL";

  function submit() {
    save.mutate(
      {
        id: competition?.id,
        input: {
          country_code: continental ? null : country.toUpperCase(),
          key: key.trim(),
          name: name.trim(),
          short_name: shortName.trim() || null,
          format,
          scope,
          tier: needsTier && tier ? Number(tier) : null,
          sort_order: Number(sortOrder) || 0,
          is_active: isActive,
        },
      },
      {
        onSuccess: () => {
          toast.success(t("common", "save"));
          onOpenChange(false);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={competition ? competition.name : "New competition"}
      description="Reference data every tenant reads. Two clubs in a division have to be choosing the same division."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            onClick={submit}
            loading={save.isPending}
            disabled={!name.trim() || !key.trim() || (needsTier && !tier)}
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" required className="sm:col-span-2">
          {(props) => (
            <Input {...props} value={name} onChange={(e) => setName(e.target.value)} />
          )}
        </Field>

        <Field label="Key" help="Stable identifier. Changing it orphans existing seasons." required>
          {(props) => (
            <Input
              {...props}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              disabled={Boolean(competition && competition.seasons > 0)}
            />
          )}
        </Field>

        <Field label="Short name">
          {(props) => (
            <Input
              {...props}
              value={shortName}
              onChange={(e) => setShortName(e.target.value)}
              maxLength={16}
            />
          )}
        </Field>

        <Field label="Scope">
          {(props) => (
            <Select
              {...props}
              value={scope}
              onChange={setScope}
              options={SCOPES.map((value) => ({ value, label: value.replace("_", " ") }))}
            />
          )}
        </Field>

        <Field label="Format">
          {(props) => (
            <Select
              {...props}
              value={format}
              onChange={setFormat}
              options={FORMATS.map((value) => ({ value, label: value.replace("_", " ") }))}
            />
          )}
        </Field>

        {!continental && (
          <Field label="Country" help="Two-letter code.">
            {(props) => (
              <Input
                {...props}
                value={country}
                onChange={(e) => setCountry(e.target.value.toUpperCase())}
                maxLength={2}
              />
            )}
          </Field>
        )}

        {needsTier && (
          <Field label="Tier" help="1 is the top flight." required>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={1}
                max={12}
                value={tier}
                onChange={(e) => setTier(e.target.value)}
              />
            )}
          </Field>
        )}

        <Field label="Sort order">
          {(props) => (
            <Input
              {...props}
              type="number"
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
            />
          )}
        </Field>

        <label className="flex items-center gap-2.5 text-sm text-text sm:col-span-2">
          <Switch checked={isActive} onChange={setIsActive} label="Offered to clubs" />
          Offered to clubs
          {competition && competition.seasons > 0 && (
            <span className="ml-2 text-xs text-text-tertiary">
              {competition.seasons} season{competition.seasons === 1 ? "" : "s"} in use
            </span>
          )}
        </label>
      </div>
    </Dialog>
  );
}

/* --- the console ------------------------------------------------------------ */

export function PlatformConsole() {
  const { t, formatNumber } = useI18n();
  const toast = useToast();

  const [search, setSearch] = useState("");
  const tenants = usePlatformTenants(search);
  const plans = usePlatformPlans();
  const competitions = usePlatformCompetitions();
  const setPlan = useSetTenantPlan();

  const [editing, setEditing] = useState<PlatformCompetition | null | undefined>(undefined);

  if (tenants.isError) {
    return (
      <ErrorState
        error={tenants.error}
        onRetry={() => void tenants.refetch()}
        title={t("common", "somethingWentWrong")}
        retryLabel={t("common", "tryAgain")}
      />
    );
  }

  const planKeys = (plans.data ?? []).map((plan) => plan.key);
  const rows = tenants.data ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={
          <>
            <Building2 className="size-3.5" />
            Platform
          </>
        }
        title="Every club on TeamSport360"
        count={rows.length}
        description="Tenants, what they are paying for, and the competitions they can enter."
      />

      <Section
        title="Tenants"
        description="Clubs and players are counted across tenants; their data is not readable from here."
        action={
          <div className="relative w-64">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-tertiary" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("common", "search")}
              className="pl-9"
            />
          </div>
        }
      >
        {tenants.isLoading ? (
          <Skeleton className="h-48" />
        ) : rows.length === 0 ? (
          <EmptyState icon={<Building2 />} title="No tenants match" />
        ) : (
          <Card className="px-4">
            <ul>
              {rows.map((tenant) => (
                <TenantRow
                  key={tenant.id}
                  tenant={tenant}
                  plans={planKeys}
                  onPlan={(plan) =>
                    setPlan.mutate(
                      { id: tenant.id, plan_key: plan },
                      {
                        onSuccess: () => toast.success(`${tenant.name} → ${plan}`),
                        // Changing a plan is behind step-up: a password-only
                        // session gets a 401 here, and saying so beats silence.
                        onError: (error) => toast.error(error.message),
                      },
                    )
                  }
                />
              ))}
            </ul>
          </Card>
        )}
      </Section>

      <Section
        title="Competitions"
        description="The pyramid every club picks from. Adding a country starts with its leagues."
        action={<Button onClick={() => setEditing(null)}>Add a competition</Button>}
      >
        {competitions.isLoading ? (
          <Skeleton className="h-48" />
        ) : (
          <Card className="px-4">
            <ul>
              {(competitions.data ?? []).map((competition) => (
                <li
                  key={competition.id}
                  className="grid items-center gap-3 border-b border-border py-3 last:border-0 sm:grid-cols-[1fr_auto_auto_auto]"
                >
                  <div className="min-w-0">
                    <p
                      className={cn(
                        "truncate text-sm font-medium",
                        competition.is_active ? "text-text" : "text-text-tertiary",
                      )}
                    >
                      {competition.name}
                    </p>
                    <p className="mt-0.5 text-xs text-text-tertiary">
                      {[
                        competition.country_code ?? "UEFA",
                        competition.format.replace("_", " ").toLowerCase(),
                        competition.tier ? `tier ${competition.tier}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>

                  <span className="text-xs tabular-nums text-text-tertiary">
                    {formatNumber(competition.seasons)}
                  </span>

                  {!competition.is_active && <Badge tone="neutral">withdrawn</Badge>}

                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditing(competition)}
                  >
                    {t("common", "edit")}
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </Section>

      <CompetitionEditor
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        competition={editing ?? null}
      />
    </div>
  );
}
