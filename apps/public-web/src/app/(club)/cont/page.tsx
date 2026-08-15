import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { preferredLocale, siteTranslator } from "@/lib/i18n";
import { formatMoney } from "@/lib/money";
import { getSite } from "@/lib/site";
import { getSupporter, getSupporterOrders } from "@/lib/supporter";
import { AccountActions, AccountForm } from "@/templates/account";
import { Eyebrow } from "@/templates/section";

/**
 * The supporter's own page.
 *
 * `/cont` in both languages — a URL is an address, and a club that switches
 * language should not have two of them for the same page.
 *
 * Never cached, never prerendered: this is one person's data, and an account
 * page served from a shared cache is the classic way to hand somebody else's
 * order history to a stranger.
 */
export const dynamic = "force-dynamic";

export const metadata = { title: "Account" };

export default async function AccountPage() {
  const site = await getSite();
  if (!site) notFound();

  const [i18n, locale, session] = await Promise.all([
    siteTranslator(site),
    preferredLocale(site),
    getSupporter(),
  ]);

  // The short-lived token lapsed. A route handler can mint a new one; a page
  // cannot write the cookie, so we go through one.
  if (session.state === "expired") redirect("/api/auth/refresh?next=/cont");

  if (session.state === "anonymous") {
    return (
      <main className="mx-auto max-w-2xl px-6 py-20 text-center">
        <Eyebrow>{i18n.t("publicSite", "myAccount")}</Eyebrow>
        <h1 className="font-display text-3xl font-extrabold tracking-[-0.02em] text-balance sm:text-4xl">
          {i18n.t("publicSite", "accountAnonTitle")}
        </h1>
        <p className="mx-auto mt-4 max-w-md text-sm/relaxed text-ink-muted">
          {i18n.t("publicSite", "accountAnonBody")}
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link
            href="/api/auth/signin?next=/cont"
            className="rounded-full px-6 py-3 text-sm font-semibold"
            style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
          >
            {i18n.t("publicSite", "signIn")}
          </Link>
          <Link
            href="/api/auth/signin?next=/cont&register=1"
            className="rounded-full border border-rule px-6 py-3 text-sm font-semibold"
          >
            {i18n.t("publicSite", "createAccount")}
          </Link>
        </div>
      </main>
    );
  }

  const supporter = session.data;
  const orders = await getSupporterOrders();
  const placed = orders.state === "ok" ? orders.data : [];

  return (
    <main className="mx-auto max-w-4xl space-y-12 px-6 py-12 sm:py-16">
      <header>
        <Eyebrow>{i18n.t("publicSite", "myAccount")}</Eyebrow>
        <h1 className="font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-[1.05] font-extrabold tracking-[-0.03em]">
          {supporter.display_name}
        </h1>
        <p className="mt-3 max-w-xl text-sm/relaxed text-ink-muted">
          {i18n.t("publicSite", "accountLead")}
        </p>
      </header>

      <section>
        <h2 className="font-display text-lg font-bold tracking-tight">
          {i18n.t("publicSite", "myOrders")}
        </h2>
        <p className="mt-1 mb-5 text-sm text-ink-muted">
          {i18n.t("publicSite", "myOrdersHint")}
        </p>

        {placed.length === 0 ? (
          <p className="rounded-xl border border-dashed border-rule px-5 py-10 text-center text-sm text-ink-muted">
            {i18n.t("publicSite", "noOrders")}
          </p>
        ) : (
          <ul className="grid gap-4">
            {placed.map((order) => (
              <li key={order.reference} className="rounded-xl border border-rule p-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <p className="tabular font-display text-base font-bold">
                    {order.reference}
                  </p>
                  <p className="tabular text-base font-semibold">
                    {formatMoney(order.total_minor, order.currency, locale)}
                  </p>
                </div>

                <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-ink-muted">
                  <span
                    className="rounded-full px-2 py-0.5 font-semibold"
                    style={{
                      background: "color-mix(in srgb, var(--brand) 10%, transparent)",
                      color: "var(--brand-text)",
                    }}
                  >
                    {i18n.t(
                      "publicSite",
                      `status${order.status}` as "statusCOLLECTED",
                    )}
                  </span>
                  {order.placed_at && (
                    <span>
                      {i18n.t("publicSite", "orderPlacedOn", {
                        date: i18n.formatDate(order.placed_at),
                      })}
                    </span>
                  )}
                  {order.collected_at && (
                    <span>
                      {i18n.t("publicSite", "orderCollectedOn", {
                        date: i18n.formatDate(order.collected_at),
                      })}
                    </span>
                  )}
                </p>

                <ul className="mt-4 grid gap-1.5 border-t border-rule pt-3">
                  {order.lines.map((line, index) => (
                    <li
                      key={`${order.reference}-${index}`}
                      className="flex items-baseline justify-between gap-4 text-sm"
                    >
                      <span className="min-w-0">
                        <span className="tabular text-ink-muted">{line.quantity}×</span>{" "}
                        {line.description}
                      </span>
                      <span className="tabular shrink-0 text-ink-muted">
                        {formatMoney(line.total_minor, order.currency, locale)}
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="font-display text-lg font-bold tracking-tight">
          {i18n.t("publicSite", "myDetails")}
        </h2>
        <p className="mt-1 mb-5 text-sm text-ink-muted">
          {i18n.t("publicSite", "myDetailsHint")}
        </p>
        <AccountForm
          supporter={supporter}
          labels={{
            name: i18n.t("publicSite", "yourName"),
            phone: i18n.t("publicSite", "phone"),
            email: i18n.t("publicSite", "email"),
            save: i18n.t("common", "save"),
            saving: i18n.t("common", "saving"),
            saved: i18n.t("publicSite", "detailsSaved"),
            failed: i18n.t("publicSite", "detailsFailed"),
            marketing: i18n.t("publicSite", "marketingOptIn"),
            marketingHint: i18n.t("publicSite", "marketingHint"),
          }}
        />
      </section>

      <AccountActions
        labels={{
          signOut: i18n.t("publicSite", "signOut"),
          closeAccount: i18n.t("publicSite", "closeAccount"),
          closeAccountHint: i18n.t("publicSite", "closeAccountHint"),
          closeAccountConfirm: i18n.t("publicSite", "closeAccountConfirm"),
        }}
      />
    </main>
  );
}
