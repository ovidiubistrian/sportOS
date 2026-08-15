import { notFound } from "next/navigation";
import { Suspense } from "react";

import { preferredLocale, siteTranslator } from "@/lib/i18n";
import { getShop, getSite } from "@/lib/site";
import { getSupporter } from "@/lib/supporter";
import { Beacon } from "@/templates/beacon";
import { Shop } from "@/templates/shop";

export const metadata = { title: "Shop" };

/**
 * Rendered per request, unlike the rest of the site.
 *
 * Reading the session cookie is what costs the page its static render — and it
 * is worth it, because the alternative is asking a signed-in supporter to type
 * their own name and email again at the till. The catalogue itself is still
 * served from the cached fetch underneath, so this costs a render, not a round
 * trip to the API.
 */
export const dynamic = "force-dynamic";

export default async function ShopPage() {
  const site = await getSite();
  if (!site) notFound();

  const [products, i18n, locale, session] = await Promise.all([
    getShop(),
    siteTranslator(site),
    preferredLocale(site),
    // Best effort: a lapsed session just means the form starts empty. This is
    // a shop, and it must not redirect somebody mid-basket to renew a token.
    getSupporter(),
  ]);

  const buyer =
    session.state === "ok"
      ? {
          name: session.data.display_name,
          email: session.data.email,
          phone: session.data.phone,
        }
      : undefined;

  return (
    <>
      {/* A club store is a destination, not a page of stock, so it opens the
          way the club's own front page does: full-bleed, in the club's colour,
          over the club's photograph. Under a plain heading the same products
          read as an inventory list — the difference is entirely the frame. */}
      <section
        className="relative isolate overflow-hidden"
        style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
      >
        {site.branding.hero_url && (
          <>
            <img
              src={site.branding.hero_url}
              alt=""
              className="absolute inset-0 -z-10 h-full w-full object-cover"
            />
            <span
              aria-hidden
              className="absolute inset-0 -z-10"
              style={{
                background:
                  "linear-gradient(to top, rgb(0 0 0 / 0.86) 0%, rgb(0 0 0 / 0.6) 45%, rgb(0 0 0 / 0.28) 100%)," +
                  "linear-gradient(to right, rgb(0 0 0 / 0.55) 0%, rgb(0 0 0 / 0.1) 60%, transparent 100%)",
              }}
            />
          </>
        )}

        <div className="mx-auto max-w-6xl px-6 py-16 sm:py-24">
          <span className="text-xs font-semibold tracking-[0.25em] uppercase opacity-80">
            {site.short_name} · {i18n.t("publicSite", "shopOfficial")}
          </span>
          <h1 className="font-display mt-4 text-[clamp(2.25rem,6vw,4.5rem)] leading-[0.95] font-extrabold tracking-[-0.03em] uppercase">
            {i18n.t("publicSite", "shop")}
          </h1>
          <p className="mt-5 max-w-md text-base/relaxed opacity-85">
            {i18n.t("publicSite", "shopLead")}
          </p>
        </div>
      </section>

      {/* Counted as a funnel step as well as a page view: "opened the shop" is
          the question, and the path alone would miss somebody who arrived by
          another route. */}
      <Suspense fallback={null}>
        <Beacon kind="SHOP_VIEW" />
      </Suspense>

      <main className="mx-auto max-w-6xl px-6 py-12">
      {products.length === 0 ? (
        <p className="text-sm text-ink-muted">{i18n.t("publicSite", "shopEmpty")}</p>
      ) : (
        <Shop
          products={products}
          locale={locale}
          buyer={buyer}
          // Resolved here because the shop is a client component and cannot
          // reach the translator, which reads request headers.
          labels={{
            addToBasket: i18n.t("publicSite", "addToBasket"),
            soldOut: i18n.t("publicSite", "soldOut"),
            lowStock: i18n.t("publicSite", "lowStock"),
            basket: i18n.t("publicSite", "basket"),
            basketEmpty: i18n.t("publicSite", "basketEmpty"),
            total: i18n.t("publicSite", "total"),
            checkout: i18n.t("publicSite", "checkout"),
            yourName: i18n.t("publicSite", "yourName"),
            email: i18n.t("publicSite", "email"),
            phone: i18n.t("publicSite", "phone"),
            note: i18n.t("publicSite", "orderNote"),
            placeOrder: i18n.t("publicSite", "placeOrder"),
            payOnCollection: i18n.t("publicSite", "payOnCollection"),
            orderPlaced: i18n.t("publicSite", "orderPlaced"),
            orderReference: i18n.t("publicSite", "orderReference"),
            orderDone: i18n.t("publicSite", "orderDone"),
            remove: i18n.t("publicSite", "remove"),
            size: i18n.t("publicSite", "size"),
            keepShopping: i18n.t("publicSite", "keepShopping"),
          }}
        />
      )}
      </main>
    </>
  );
}
