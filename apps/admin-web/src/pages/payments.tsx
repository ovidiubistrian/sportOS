import {
  ApiError,
  useCheckPaymentGateway,
  usePaymentCalls,
  usePaymentGateways,
  useSavePaymentGateway,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  PageHeader,
  Skeleton,
  Switch,
  useToast,
} from "@footbola/ui";
import { CreditCard, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";
import { useStepUp } from "../app/step-up";

/**
 * Where a club sets up taking cards.
 *
 * One gateway so far, BT iPay, and the screen is shaped around what its bank
 * actually gives a club: a user name, a password, and a decision about whether
 * this is the test gateway or the real one.
 *
 * Two things about it are not decoration.
 *
 * The password is write-only. It is never sent back, so the field is empty even
 * for a club that has one — the badge beside it says whether it does, which is
 * all anybody needs to know. Leaving it blank on a later save keeps the stored
 * one rather than clearing it, because a club that cannot read a value cannot
 * retype it.
 *
 * Saving demands a second factor. `useStepUp` runs the save, and if the API
 * asks for one it opens a small window, waits, and runs the save again — so
 * the form is still filled in when it succeeds. Nobody is asked for a code
 * merely for looking at this page.
 */

const PROVIDER = "btipay";

export function PaymentsPage() {
  const { t } = useI18n();
  const { can } = useSession();
  const toast = useToast();
  const withStepUp = useStepUp();

  const gateways = usePaymentGateways();
  const save = useSavePaymentGateway();
  const check = useCheckPaymentGateway();
  const calls = usePaymentCalls({ limit: 20 });

  const gateway = gateways.data?.find((row) => row.provider === PROVIDER);
  const mayManage = can("payments.settings.manage");

  const [userName, setUserName] = useState("");
  const [password, setPassword] = useState("");
  const [sandbox, setSandbox] = useState(true);
  const [isLive, setIsLive] = useState(false);
  const [checked, setChecked] = useState<{ ok: boolean; error?: string | null } | null>(null);

  // Load what is stored once it arrives, and again if it changes underneath —
  // but never over something half-typed.
  useEffect(() => {
    if (!gateway) return;
    setUserName(gateway.user_name);
    setSandbox(gateway.sandbox);
    setIsLive(gateway.is_live);
  }, [gateway]);

  const onSave = async () => {
    try {
      await withStepUp(() =>
        save.mutateAsync({
          provider: PROVIDER,
          settings: {
            user_name: userName.trim(),
            // Omitted rather than sent empty: empty would mean "clear it".
            ...(password ? { password } : {}),
            sandbox,
            is_live: isLive,
          },
        }),
      );
      setPassword("");
      setChecked(null);
      toast.success(t("payments", "saved"));
    } catch (error) {
      if (error instanceof ApiError) {
        toast.error(t("site", "couldNotSave"), error.message);
      }
    }
  };

  const onCheck = async () => {
    try {
      const result = await withStepUp(() => check.mutateAsync({ provider: PROVIDER }));
      setChecked(result);
    } catch (error) {
      if (error instanceof ApiError) {
        setChecked({ ok: false, error: error.message });
      }
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <>
            <CreditCard className="size-3.5" />
            {t("payments", "eyebrow")}
          </>
        }
        title={t("payments", "title")}
        description={t("payments", "description")}
      />

      {gateways.isLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <Card className="max-w-2xl space-y-5 p-5">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-text">BT iPay</p>
            <div className="flex items-center gap-2">
              {gateway?.has_password && (
                <Badge tone="outline">{t("payments", "passwordStored")}</Badge>
              )}
              <Badge tone={gateway?.is_live ? "success" : "outline"} dot>
                {gateway?.is_live ? t("payments", "live") : t("payments", "notLive")}
              </Badge>
            </div>
          </div>

          <Field label={t("payments", "userName")} htmlFor="btipay-user">
            {(props) => (
              <Input
                {...props}
                value={userName}
                disabled={!mayManage}
                autoComplete="off"
                onChange={(event) => setUserName(event.target.value)}
              />
            )}
          </Field>

          <Field
            label={t("payments", "password")}
            htmlFor="btipay-password"
            help={
              gateway?.has_password
                ? t("payments", "passwordKeptHint")
                : t("payments", "passwordHint")
            }
          >
            {(props) => (
              <Input
                {...props}
                type="password"
                value={password}
                disabled={!mayManage}
                autoComplete="new-password"
                placeholder={gateway?.has_password ? "••••••••" : ""}
                onChange={(event) => setPassword(event.target.value)}
              />
            )}
          </Field>

          <div className="space-y-1">
            <Switch
              checked={sandbox}
              disabled={!mayManage}
              onChange={setSandbox}
              label={t("payments", "sandbox")}
            />
            <p className="text-xs text-text-secondary">{t("payments", "sandboxHint")}</p>
          </div>

          <div className="space-y-1">
            <Switch
              checked={isLive}
              disabled={!mayManage}
              onChange={setIsLive}
              label={t("payments", "acceptCards")}
            />
            <p className="text-xs text-text-secondary">{t("payments", "acceptCardsHint")}</p>
          </div>

          {checked && (
            <p
              className={`text-sm ${checked.ok ? "text-success" : "text-danger"}`}
              role="status"
            >
              {checked.ok ? t("payments", "checkPassed") : checked.error}
            </p>
          )}

          {mayManage && (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                loading={save.isPending}
                disabled={!userName.trim() || (!password && !gateway?.has_password)}
                onClick={onSave}
              >
                {t("common", "save")}
              </Button>
              <Button
                variant="secondary"
                loading={check.isPending}
                disabled={!gateway}
                onClick={onCheck}
              >
                <ShieldCheck />
                {t("payments", "check")}
              </Button>
            </div>
          )}
        </Card>
      )}

      {/* What was said to the bank. A club arguing with BT about a payment is
          arguing about what was submitted, and this is the record of it. */}
      <Card className="max-w-4xl p-5">
        <p className="text-sm font-medium text-text">{t("payments", "callsTitle")}</p>
        <p className="mt-0.5 text-xs text-text-secondary">{t("payments", "callsHint")}</p>

        {calls.isLoading ? (
          <Skeleton className="mt-4 h-24" />
        ) : !calls.data?.data.length ? (
          <p className="mt-4 text-sm text-text-tertiary">{t("payments", "noCalls")}</p>
        ) : (
          <ul className="mt-4 divide-y divide-border">
            {calls.data.data.map((call) => (
              <li key={call.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                <Badge tone={call.ok ? "success" : "danger"} size="sm">
                  {call.ok ? "ok" : (call.error_code ?? "error")}
                </Badge>
                <span className="font-mono text-xs text-text-secondary">
                  {call.endpoint.replace("/payment/rest/", "")}
                </span>
                {call.order_ref && (
                  <span className="text-xs text-text-tertiary">{call.order_ref}</span>
                )}
                <span className="ml-auto text-xs text-text-tertiary" data-numeric>
                  {call.latency_ms != null ? `${call.latency_ms} ms` : ""}
                </span>
                <span className="text-xs text-text-tertiary" data-numeric>
                  {new Date(call.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
