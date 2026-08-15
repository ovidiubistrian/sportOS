"use client";

import { useEffect, useState } from "react";

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
    if (ok) onChanged(body as unknown as Basket);
    else setError(errorFrom(body));
  }

  return (
    <article className="flex flex-col overflow-hidden rounded-lg border border-rule">
      <div className="aspect-square bg-[color-mix(in_srgb,var(--brand)_6%,transparent)]">
        {product.cover_url && (
          <img
            src={product.cover_url}
            alt=""
            className="h-full w-full object-cover"
            loading="lazy"
          />
        )}
      </div>

      <div className="flex flex-1 flex-col p-4">
        <h3 className="font-display text-base leading-tight font-bold text-balance">
          {product.name}
        </h3>
        {product.description && (
          <p className="mt-1.5 line-clamp-2 text-xs text-ink-muted">{product.description}</p>
        )}

        <p className="tabular mt-3 text-lg font-semibold">
          {formatMoney(product.price_minor, product.currency, locale)}
        </p>

        {/* Only shown when there is a choice to make. */}
        {product.variants.length > 1 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {product.variants.map((variant) => (
              <button
                key={variant.id}
                type="button"
                disabled={variant.stock === 0}
                onClick={() => setVariantId(variant.id)}
                aria-pressed={variant.id === variantId}
                className="rounded-sm border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-35"
                style={
                  variant.id === variantId
                    ? {
                        background: "var(--brand)",
                        color: "var(--brand-contrast)",
                        borderColor: "var(--brand)",
                      }
                    : { borderColor: "var(--rule, #ddd)" }
                }
              >
                {variant.label}
              </button>
            ))}
          </div>
        )}

        {chosen && chosen.stock > 0 && chosen.stock <= 5 && (
          <p className="mt-2 text-xs font-medium text-ink-muted">
            {labels.lowStock.replace("{count}", String(chosen.stock))}
          </p>
        )}
        {error && <p className="mt-2 text-xs font-medium text-[#b3352c]">{error}</p>}

        <button
          type="button"
          disabled={soldOut || busy || !chosen}
          onClick={add}
          className="mt-4 w-full rounded-sm px-4 py-2.5 text-xs font-bold tracking-widest uppercase transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
        >
          {soldOut ? labels.soldOut : labels.addToBasket}
        </button>
      </div>
    </article>
  );
}

/* --- the shop -------------------------------------------------------------- */

export function Shop({
  products,
  locale,
  labels,
}: {
  products: ShopProduct[];
  locale: string;
  labels: ShopLabels;
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
    <div className="grid gap-10 lg:grid-cols-[1fr_20rem]">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
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
}: {
  basket: Basket | null;
  locale: string;
  labels: ShopLabels;
  onChanged: (basket: Basket) => void;
  onPlaced: (reference: string) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
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
    if (ok) onPlaced(String((body as { reference?: string }).reference ?? ""));
    else setError(errorFrom(body));
  }

  return (
    <aside className="h-fit rounded-lg border border-rule p-5 lg:sticky lg:top-20">
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
            className="mt-3 w-full rounded-sm px-4 py-3 text-xs font-bold tracking-widest uppercase transition-opacity hover:opacity-90 disabled:opacity-40"
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
      className="w-full rounded-sm border border-rule bg-transparent px-3 py-2 text-sm outline-none focus:border-[var(--brand)]"
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
