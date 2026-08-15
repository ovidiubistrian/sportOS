"use client";

import { useEffect, useState } from "react";

import { track } from "./beacon";

import { formatMoney } from "@/lib/money";
import type { Basket, ShopProduct } from "@/lib/site";

/**
 * The shop, as a supporter uses it.
 *
 * Client-side because a basket is the one thing on a club site that changes
 * without navigating. It talks to `/api/basket` on this same origin — the Next
 * route handler proxies to the API and holds the cart token in an httpOnly
 * cookie, so no token is ever in this component's hands.
 *
 * Stock counts are shown as numbers, not as "in stock": a supporter looking at
 * "2 left" buys today, and a club that sells the last one owes the next person
 * an honest page.
 */

export interface ShopLabels {
  addToBasket: string;
  soldOut: string;
  lowStock: string;
  basket: string;
  basketEmpty: string;
  total: string;
  checkout: string;
  yourName: string;
  email: string;
  phone: string;
  note: string;
  placeOrder: string;
  payOnCollection: string;
  orderPlaced: string;
  orderReference: string;
  orderDone: string;
  remove: string;
  size: string;
  keepShopping: string;
}

async function call(
  path: string,
  init?: RequestInit,
): Promise<{ ok: boolean; body: Record<string, unknown> }> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json" },
  });
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, body };
}

function errorFrom(body: Record<string, unknown>): string {
  const message = body?.message;
  return typeof message === "string" ? message : "Something went wrong.";
}

/* --- one product ----------------------------------------------------------- */

export function ProductCard({
  product,
  locale,
  labels,
  onChanged,
}: {
  product: ShopProduct;
  locale: string;
  labels: ShopLabels;
  onChanged: (basket: Basket) => void;
}) {
  const inStock = product.variants.filter((variant) => variant.stock > 0);
  const [variantId, setVariantId] = useState(inStock[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chosen = product.variants.find((variant) => variant.id === variantId);
  const soldOut = inStock.length === 0;

  async function add() {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    const { ok, body } = await call("/api/basket", {
      method: "PUT",
      body: JSON.stringify({ variant_id: chosen.id, quantity: 1 }),
    });
    setBusy(false);
    if (ok) {
      onChanged(body as unknown as Basket);
      track("BASKET_ADD");
    } else {
      setError(errorFrom(body));
    }
  }

  /* Borderless, the way a shop shows a product: the picture is the card, the
     words sit under it, and nothing draws a box around either. A border here
     turns a wall of merchandise into a spreadsheet — which is what this looked
     like before.

     The add button lives *over* the image and appears on hover, so the grid
     stays quiet while browsing and the action is exactly where the eye already
     is. On a phone there is no hover, so it is always visible; `md:` guards
     every part of that. */
  return (
    <article className="group flex flex-col">
      <div
        className="relative aspect-square overflow-hidden rounded-xl"
        style={{ background: "color-mix(in srgb, var(--brand) 5%, transparent)" }}
      >
        {product.cover_url && (
          <img
            src={product.cover_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.04]"
          />
        )}

        {soldOut && (
          <span className="absolute top-3 left-3 rounded-full bg-ink/85 px-2.5 py-1 text-[10px] font-bold tracking-widest text-page uppercase">
            {labels.soldOut}
          </span>
        )}
        {!soldOut && chosen && chosen.stock <= 5 && (
          <span
            className="absolute top-3 left-3 rounded-full px-2.5 py-1 text-[10px] font-bold tracking-widest uppercase"
            style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
          >
            {labels.lowStock.replace("{count}", String(chosen.stock))}
          </span>
        )}

        {!soldOut && (
          <div className="absolute inset-x-2 bottom-2 md:pointer-events-none md:opacity-0 md:transition-opacity md:duration-200 md:group-hover:pointer-events-auto md:group-hover:opacity-100 md:focus-within:pointer-events-auto md:focus-within:opacity-100">
            <button
              type="button"
              disabled={busy || !chosen}
              onClick={add}
              className="w-full rounded-lg px-4 py-3 text-xs font-bold tracking-widest uppercase shadow-lg transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
            >
              {labels.addToBasket}
            </button>
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col pt-3.5">
        <h3 className="text-sm leading-snug font-semibold text-balance">{product.name}</h3>
        <p className="tabular mt-1 text-sm font-bold">
          {formatMoney(product.price_minor, product.currency, locale)}
        </p>

        {/* Sizes only when there is a choice to make, and quiet until chosen —
            a row of hard-outlined chips under every card is most of what made
            the old grid noisy. */}
        {product.variants.length > 1 && (
          <div className="mt-2.5 flex flex-wrap gap-1">
            {product.variants.map((variant) => (
              <button
                key={variant.id}
                type="button"
                disabled={variant.stock === 0}
                onClick={() => setVariantId(variant.id)}
                aria-pressed={variant.id === variantId}
                aria-label={variant.label}
                className="min-w-8 rounded-md px-2 py-1 text-[11px] font-semibold transition-colors disabled:line-through disabled:opacity-30"
                style={
                  variant.id === variantId
                    ? { background: "var(--brand)", color: "var(--brand-contrast)" }
                    : { background: "color-mix(in srgb, var(--brand) 8%, transparent)" }
                }
              >
                {variant.label}
              </button>
            ))}
          </div>
        )}

        {error && <p className="mt-2 text-xs font-medium text-danger">{error}</p>}
      </div>
    </article>
  );
}

/* --- the shop -------------------------------------------------------------- */

export interface Buyer {
  name: string;
  email: string | null;
  phone: string | null;
}

export function Shop({
  products,
  locale,
  labels,
  buyer,
}: {
  products: ShopProduct[];
  locale: string;
  labels: ShopLabels;
  /** Filled in when somebody is signed in. A supporter who has already told
      the club who they are should not be asked again at the till. */
  buyer?: Buyer;
}) {
  const [basket, setBasket] = useState<Basket | null>(null);
  const [placed, setPlaced] = useState<{ reference: string } | null>(null);

  useEffect(() => {
    // A basket survives a reload, so the page has to ask what is in it rather
    // than assume it starts empty.
    void call("/api/basket").then(({ ok, body }) => {
      if (ok) setBasket(body as unknown as Basket);
    });
  }, []);

  if (placed) {
    return (
      <OrderConfirmation
        reference={placed.reference}
        labels={labels}
        onDone={() => {
          setPlaced(null);
          void call("/api/basket").then(({ ok, body }) => {
            if (ok) setBasket(body as unknown as Basket);
          });
        }}
      />
    );
  }

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_21rem] lg:items-start">
      {/* Two across on a phone, because merchandise is browsed by picture and
          one-per-row makes a ten-item shop feel like a hundred. */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-8 sm:gap-x-5 xl:grid-cols-3">
        {products.map((product) => (
          <ProductCard
            key={product.id}
            product={product}
            locale={locale}
            labels={labels}
            onChanged={setBasket}
          />
        ))}
      </div>

      <BasketPanel
        basket={basket}
        locale={locale}
        labels={labels}
        buyer={buyer}
        onChanged={setBasket}
        onPlaced={(reference) => {
          setBasket(null);
          setPlaced({ reference });
        }}
      />
    </div>
  );
}

/* --- basket and checkout --------------------------------------------------- */

function BasketPanel({
  basket,
  locale,
  labels,
  onChanged,
  onPlaced,
  buyer,
}: {
  basket: Basket | null;
  locale: string;
  labels: ShopLabels;
  onChanged: (basket: Basket) => void;
  onPlaced: (reference: string) => void;
  buyer?: Buyer;
}) {
  const [name, setName] = useState(buyer?.name ?? "");
  const [email, setEmail] = useState(buyer?.email ?? "");
  const [phone, setPhone] = useState(buyer?.phone ?? "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lines = basket?.lines ?? [];

  async function setQuantity(variantId: string, quantity: number) {
    const { ok, body } = await call("/api/basket", {
      method: "PUT",
      body: JSON.stringify({ variant_id: variantId, quantity }),
    });
    if (ok) onChanged(body as unknown as Basket);
    else setError(errorFrom(body));
  }

  async function place() {
    setBusy(true);
    setError(null);
    // Reported before the call, not after: a checkout somebody started and
    // abandoned because the last shirt sold is exactly the step a club wants
    // to see in the funnel.
    track("CHECKOUT");
    const { ok, body } = await call("/api/basket/checkout", {
      method: "POST",
      body: JSON.stringify({
        name: name.trim(),
        email: email.trim() || null,
        phone: phone.trim() || null,
        note: note.trim() || null,
      }),
    });
    setBusy(false);
    if (ok) {
      track("ORDER", { value_minor: basket?.total_minor ?? undefined });
      onPlaced(String((body as { reference?: string }).reference ?? ""));
    } else {
      setError(errorFrom(body));
    }
  }

  return (
    <aside
      className="h-fit rounded-2xl p-5 lg:sticky lg:top-24"
      style={{ background: "color-mix(in srgb, var(--brand) 5%, transparent)" }}
    >
      <h2 className="font-display mb-4 text-xs font-bold tracking-[0.2em] text-ink-muted uppercase">
        {labels.basket}
      </h2>

      {lines.length === 0 ? (
        <p className="text-sm text-ink-muted">{labels.basketEmpty}</p>
      ) : (
        <>
          <ul className="divide-y divide-rule border-y border-rule">
            {lines.map((line) => (
              <li key={line.variant_id} className="flex items-start gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{line.product_name}</p>
                  <p className="mt-0.5 text-xs text-ink-muted">
                    {labels.size}: {line.variant_label}
                  </p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <button
                      type="button"
                      aria-label="-"
                      onClick={() => void setQuantity(line.variant_id, line.quantity - 1)}
                      className="grid size-6 place-items-center rounded border border-rule text-sm"
                    >
                      −
                    </button>
                    <span className="tabular w-5 text-center text-sm">{line.quantity}</span>
                    <button
                      type="button"
                      aria-label="+"
                      onClick={() => void setQuantity(line.variant_id, line.quantity + 1)}
                      className="grid size-6 place-items-center rounded border border-rule text-sm"
                    >
                      +
                    </button>
                    <button
                      type="button"
                      onClick={() => void setQuantity(line.variant_id, 0)}
                      className="ml-1 text-xs text-ink-faint underline"
                    >
                      {labels.remove}
                    </button>
                  </div>
                </div>
                <span className="tabular text-sm font-semibold">
                  {formatMoney(line.total_minor, basket!.currency, locale)}
                </span>
              </li>
            ))}
          </ul>

          <p className="mt-4 flex items-baseline justify-between">
            <span className="text-sm text-ink-muted">{labels.total}</span>
            <span className="tabular font-display text-xl font-bold">
              {formatMoney(basket!.total_minor, basket!.currency, locale)}
            </span>
          </p>

          <div className="mt-5 space-y-2.5">
            <Input value={name} onChange={setName} placeholder={labels.yourName} required />
            <Input value={email} onChange={setEmail} placeholder={labels.email} type="email" />
            <Input value={phone} onChange={setPhone} placeholder={labels.phone} type="tel" />
            <Input value={note} onChange={setNote} placeholder={labels.note} />
          </div>

          {error && <p className="mt-3 text-xs font-medium text-[#b3352c]">{error}</p>}

          <p className="mt-3 text-xs text-ink-muted">{labels.payOnCollection}</p>

          <button
            type="button"
            disabled={busy || name.trim().length < 2}
            onClick={place}
            className="mt-3 w-full rounded-full px-4 py-3.5 text-xs font-bold tracking-widest uppercase transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
          >
            {labels.placeOrder}
          </button>
        </>
      )}
    </aside>
  );
}

function Input({
  value,
  onChange,
  placeholder,
  type = "text",
  required,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  type?: string;
  required?: boolean;
}) {
  return (
    <input
      type={type}
      value={value}
      required={required}
      aria-label={placeholder}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-lg border border-rule bg-transparent px-3.5 py-2.5 text-sm outline-none transition-colors focus:border-[var(--brand)]"
    />
  );
}

function OrderConfirmation({
  reference,
  labels,
  onDone,
}: {
  reference: string;
  labels: ShopLabels;
  onDone: () => void;
}) {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <p className="font-display text-xs font-bold tracking-[0.2em] text-ink-muted uppercase">
        {labels.orderPlaced}
      </p>
      <p
        className="tabular font-display mt-4 text-4xl font-extrabold tracking-widest"
        style={{ color: "var(--brand)" }}
      >
        {reference}
      </p>
      <p className="mt-4 text-sm text-ink-muted">{labels.orderReference}</p>
      <button
        type="button"
        onClick={onDone}
        className="mt-8 rounded-sm px-6 py-3 text-xs font-bold tracking-widest uppercase"
        style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
      >
        {labels.keepShopping}
      </button>
    </div>
  );
}
