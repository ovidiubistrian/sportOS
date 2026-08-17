"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { formatMoney } from "@/lib/money";
import type { TicketEventDetail, TicketLayoutSection } from "@/lib/site";

/**
 * Choosing a seat, as a supporter does it on a phone in a queue.
 *
 * Three deliberate decisions.
 *
 * **Drill down, do not pinch.** The overview shows sectors; tapping one opens
 * its seats. A thirty-thousand-seat map that a supporter has to zoom into with
 * two fingers on a bus is not a seat picker, it is a puzzle. The admin editor
 * pans and zooms because an administrator is at a desk doing precise work;
 * this is a different job and gets a different interaction, which is why it is
 * a separate component rather than the same one reskinned.
 *
 * **The countdown is honest.** It counts the *server's* expiry, not ten
 * minutes from when the component rendered, and when it reaches zero the seats
 * are gone — so the page says so and clears the selection rather than letting
 * somebody fill in a form for a reservation that no longer exists.
 *
 * **Nothing internal leaks.** A seat is free or it is not. Held for a sponsor,
 * blocked for a camera platform, sitting in somebody else's basket — all the
 * same grey. The API already refuses to say which; this makes sure the screen
 * does not invent a distinction either.
 */

export interface TicketLabels {
  chooseSector: string;
  chooseSeats: string;
  back: string;
  available: string;
  unavailable: string;
  selected: string;
  soldOut: string;
  from: string;
  yourSeats: string;
  noneChosen: string;
  bestAvailable: string;
  howMany: string;
  holdExpires: string;
  holdExpired: string;
  total: string;
  yourName: string;
  email: string;
  phone: string;
  payAtCounter: string;
  payByCard: string;
  cardSafe: string;
  buy: string;
  orderPlaced: string;
  orderReference: string;
  showTickets: string;
  generalAdmission: string;
  seatsLeft: string;
  remove: string;
  standing: string;
}

interface Seat {
  id: string;
  row: string | null;
  seat: string | null;
  index: number;
  kind: string;
  zone: string | null;
  available: boolean;
}

interface Held {
  id: string;
  stand: string;
  section: string;
  row: string | null;
  seat: string | null;
  zone: string | null;
}

async function call(body: Record<string, unknown>) {
  const response = await fetch("/api/tickets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  return { ok: response.ok, body: payload };
}

function messageFrom(body: Record<string, unknown>): string {
  const message = body.message;
  return typeof message === "string" ? message : "";
}

function seatName(seat: { row: string | null; seat: string | null }): string {
  if (!seat.row && !seat.seat) return "";
  return `${seat.row ?? ""}${seat.seat ?? ""}`;
}

export function TicketPicker({
  event,
  labels,
  locale,
}: {
  event: TicketEventDetail;
  labels: TicketLabels;
  locale: string;
}) {
  const [sectionId, setSectionId] = useState<string | null>(null);
  const [seats, setSeats] = useState<Seat[]>([]);
  const [loadingSeats, setLoadingSeats] = useState(false);
  const [held, setHeld] = useState<Held[]>([]);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [placed, setPlaced] = useState<{ reference: string } | null>(null);
  const [quantity, setQuantity] = useState(2);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");

  const summaryRef = useRef<HTMLDivElement>(null);

  const sections = useMemo(() => {
    const byId = new Map<string, TicketLayoutSection & { stand: string }>();
    for (const stand of event.layout.stands) {
      for (const section of stand.sections) {
        byId.set(section.id, { ...section, stand: stand.name });
      }
    }
    return byId;
  }, [event.layout.stands]);

  const availability = useMemo(() => {
    const byId = new Map(event.availability.map((row) => [row.section_id, row]));
    return byId;
  }, [event.availability]);

  const currentSection = sectionId ? sections.get(sectionId) : null;

  /** The countdown, driven by the server's expiry rather than by a local clock. */
  useEffect(() => {
    if (!expiresAt) {
      setRemaining(0);
      return;
    }
    const tick = () => {
      const left = Math.max(0, Math.round((expiresAt - Date.now()) / 1000));
      setRemaining(left);
      if (left === 0) {
        // The seats are genuinely gone. Saying so and clearing the selection
        // beats letting somebody fill in a form for a lapsed reservation.
        setHeld([]);
        setExpiresAt(null);
        setError(labels.holdExpired);
      }
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [expiresAt, labels.holdExpired]);

  const loadSeats = useCallback(
    async (id: string) => {
      setLoadingSeats(true);
      setError(null);
      try {
        const response = await fetch(
          `/api/tickets?slug=${encodeURIComponent(event.slug)}&section_id=${encodeURIComponent(id)}`,
        );
        const body = (await response.json()) as { seats?: Seat[] };
        setSeats(body.seats ?? []);
      } catch {
        setSeats([]);
      } finally {
        setLoadingSeats(false);
      }
    },
    [event.slug],
  );

  const openSection = (id: string) => {
    setSectionId(id);
    const section = sections.get(id);
    if (section?.kind === "RESERVED") void loadSeats(id);
    else setSeats([]);
  };

  const applyHold = (body: Record<string, unknown>) => {
    const rows = (body.seats as Held[] | undefined) ?? [];
    setHeld(rows);
    const expiry = body.expires_at;
    setExpiresAt(typeof expiry === "string" ? new Date(expiry).getTime() : null);
  };

  /**
   * Selecting a seat sends the *whole* selection, not a delta.
   *
   * The server replaces the hold each time, so the seats it is holding and the
   * ones highlighted here cannot drift apart — which they do the moment two
   * requests cross on a bad connection.
   */
  const toggleSeat = async (seat: Seat) => {
    if (!seat.available && !held.some((row) => row.id === seat.id)) return;

    const next = held.some((row) => row.id === seat.id)
      ? held.filter((row) => row.id !== seat.id).map((row) => row.id)
      : [...held.map((row) => row.id), seat.id];

    if (next.length === 0) {
      setBusy(true);
      await call({ action: "release", slug: event.slug });
      setHeld([]);
      setExpiresAt(null);
      setBusy(false);
      return;
    }

    setBusy(true);
    setError(null);
    const { ok, body } = await call({
      action: "hold",
      slug: event.slug,
      inventory_ids: next,
      ticket_type_code: "ADULT",
    });
    if (ok) {
      applyHold(body);
      if (sectionId) void loadSeats(sectionId);
    } else {
      setError(messageFrom(body));
      if (sectionId) void loadSeats(sectionId);
    }
    setBusy(false);
  };

  const pickBest = async () => {
    setBusy(true);
    setError(null);
    const { ok, body } = await call({
      action: "best-available",
      slug: event.slug,
      quantity,
      section_id: sectionId,
      ticket_type_code: "ADULT",
    });
    if (ok) {
      applyHold(body);
      if (sectionId) void loadSeats(sectionId);
      summaryRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else {
      setError(messageFrom(body));
    }
    setBusy(false);
  };

  const buy = async (method: "ON_COLLECTION" | "CARD") => {
    setBusy(true);
    setError(null);
    const { ok, body } = await call({
      action: "checkout",
      slug: event.slug,
      name,
      email: email || null,
      phone: phone || null,
      payment_method: method,
    });
    if (ok) {
      setPlaced({ reference: String(body.reference ?? "") });
      setHeld([]);
      setExpiresAt(null);
    } else {
      setError(messageFrom(body));
      setBusy(false);
    }
  };

  const priceFor = (zone: string | null): number | null => {
    if (!zone) return null;
    return event.prices[zone]?.amount_minor ?? null;
  };

  const total = held.reduce((sum, row) => sum + (priceFor(row.zone) ?? 0), 0);

  if (placed) {
    return (
      <div className="rounded-2xl border border-rule bg-page p-8 text-center">
        <p className="text-lg font-semibold">{labels.orderPlaced}</p>
        <p className="mt-2 text-sm text-ink-muted">{labels.orderReference}</p>
        <p className="mt-1 font-mono text-2xl tracking-wider">{placed.reference}</p>
        <a
          href={`/bilete/comanda/${placed.reference}`}
          className="mt-6 inline-block rounded-full bg-brand px-6 py-3 text-sm font-medium text-brand-contrast"
        >
          {labels.showTickets}
        </a>
      </div>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0">
        {!currentSection ? (
          <SectorOverview
            event={event}
            labels={labels}
            onOpen={openSection}
            availability={availability}
            priceFor={priceFor}
            locale={locale}
          />
        ) : (
          <div>
            <button
              type="button"
              onClick={() => {
                setSectionId(null);
                setSeats([]);
              }}
              className="mb-4 text-sm text-ink-muted underline-offset-4 hover:underline"
            >
              ← {labels.back}
            </button>

            <h2 className="text-lg font-semibold">{currentSection.name}</h2>
            <p className="text-sm text-ink-muted">{currentSection.stand}</p>

            {currentSection.kind === "GENERAL_ADMISSION" ? (
              <GeneralAdmission
                labels={labels}
                available={availability.get(currentSection.id)?.available ?? 0}
                quantity={quantity}
                onQuantity={setQuantity}
                onPick={pickBest}
                busy={busy}
              />
            ) : loadingSeats ? (
              <p className="mt-6 text-sm text-ink-muted">…</p>
            ) : (
              <SeatGrid
                seats={seats}
                held={held}
                labels={labels}
                busy={busy}
                priceFor={priceFor}
                locale={locale}
                currency={event.currency}
                onToggle={toggleSeat}
              />
            )}
          </div>
        )}
      </div>

      {/* Sticky on desktop, and pinned to the bottom on a phone — the summary
          is the one thing a supporter must never have to scroll to find. */}
      <div
        ref={summaryRef}
        className="lg:sticky lg:top-6 lg:self-start"
        aria-live="polite"
      >
        <div className="rounded-2xl border border-rule bg-page p-5">
          <p className="text-xs uppercase tracking-[0.18em] text-ink-muted">
            {labels.yourSeats}
          </p>

          {held.length === 0 ? (
            <p className="mt-3 text-sm text-ink-muted">{labels.noneChosen}</p>
          ) : (
            <>
              {expiresAt && (
                <p className="mt-3 rounded-lg bg-brand/10 px-3 py-2 text-sm">
                  {labels.holdExpires}{" "}
                  <span className="font-medium tabular-nums">
                    {Math.floor(remaining / 60)}:
                    {String(remaining % 60).padStart(2, "0")}
                  </span>
                </p>
              )}

              <ul className="mt-3 space-y-2">
                {held.map((row) => (
                  <li key={row.id} className="flex items-baseline gap-2 text-sm">
                    <span className="min-w-0 flex-1 truncate">
                      {row.section}
                      {seatName(row) ? ` · ${seatName(row)}` : ` · ${labels.standing}`}
                    </span>
                    <span className="tabular-nums">
                      {formatMoney(priceFor(row.zone) ?? 0, event.currency, locale)}
                    </span>
                  </li>
                ))}
              </ul>

              <div className="mt-4 flex items-baseline justify-between border-t border-rule pt-3">
                <span className="text-sm">{labels.total}</span>
                <span className="text-lg font-semibold tabular-nums">
                  {formatMoney(total, event.currency, locale)}
                </span>
              </div>

              <div className="mt-4 space-y-2">
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={labels.yourName}
                  aria-label={labels.yourName}
                  className="w-full rounded-lg border border-rule px-3 py-2 text-sm"
                />
                <input
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={labels.email}
                  aria-label={labels.email}
                  type="email"
                  className="w-full rounded-lg border border-rule px-3 py-2 text-sm"
                />
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder={labels.phone}
                  aria-label={labels.phone}
                  className="w-full rounded-lg border border-rule px-3 py-2 text-sm"
                />
              </div>

              <button
                type="button"
                disabled={busy || !name.trim() || remaining === 0}
                onClick={() => void buy("ON_COLLECTION")}
                className="mt-3 w-full rounded-full bg-brand px-5 py-3 text-sm font-medium text-brand-contrast disabled:opacity-50"
              >
                {labels.buy}
              </button>
              <p className="mt-2 text-center text-xs text-ink-muted">
                {labels.payAtCounter}
              </p>
            </>
          )}

          {error && (
            <p role="alert" className="mt-3 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function SectorOverview({
  event,
  labels,
  onOpen,
  availability,
  priceFor,
  locale,
}: {
  event: TicketEventDetail;
  labels: TicketLabels;
  onOpen: (id: string) => void;
  availability: Map<string, { available: number; total: number }>;
  priceFor: (zone: string | null) => number | null;
  locale: string;
}) {
  return (
    <div>
      <h2 className="text-lg font-semibold">{labels.chooseSector}</h2>

      <div className="mt-4 space-y-5">
        {event.layout.stands.map((stand) => (
          <section key={stand.id}>
            <h3 className="text-xs uppercase tracking-[0.18em] text-ink-muted">
              {stand.name}
            </h3>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2">
              {stand.sections.map((section) => {
                const free = availability.get(section.id)?.available ?? 0;
                const price = priceFor(section.price_zone?.code ?? null);
                const soldOut = free === 0;

                return (
                  <li key={section.id}>
                    <button
                      type="button"
                      disabled={soldOut}
                      onClick={() => onOpen(section.id)}
                      className="flex w-full items-center gap-3 rounded-xl border border-rule bg-page p-3 text-left transition-colors enabled:hover:border-brand disabled:opacity-50"
                    >
                      <span
                        className="h-9 w-1.5 shrink-0 rounded-full"
                        style={{ backgroundColor: section.price_zone?.colour ?? "#94a3b8" }}
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">
                          {section.name}
                        </span>
                        <span className="block text-xs text-ink-muted">
                          {soldOut
                            ? labels.soldOut
                            : `${free} ${labels.seatsLeft}`}
                        </span>
                      </span>
                      {price !== null && (
                        <span className="shrink-0 text-sm tabular-nums">
                          {labels.from} {formatMoney(price, event.currency, locale)}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>

      <ul className="mt-6 flex flex-wrap gap-x-4 gap-y-2">
        {event.layout.price_zones.map((zone) => (
          <li key={zone.id} className="flex items-center gap-2 text-xs text-ink-muted">
            <span
              className="size-3 rounded-sm"
              style={{ backgroundColor: zone.colour }}
              aria-hidden
            />
            {zone.name}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SeatGrid({
  seats,
  held,
  labels,
  busy,
  priceFor,
  locale,
  currency,
  onToggle,
}: {
  seats: Seat[];
  held: Held[];
  labels: TicketLabels;
  busy: boolean;
  priceFor: (zone: string | null) => number | null;
  locale: string;
  currency: string;
  onToggle: (seat: Seat) => void;
}) {
  const chosen = new Set(held.map((row) => row.id));

  const rows = useMemo(() => {
    const byRow = new Map<string, Seat[]>();
    for (const seat of seats) {
      const key = seat.row ?? "";
      const list = byRow.get(key) ?? [];
      list.push(seat);
      byRow.set(key, list);
    }
    return [...byRow.entries()].map(([label, list]) => ({
      label,
      seats: list.sort((a, b) => a.index - b.index),
    }));
  }, [seats]);

  return (
    <div className="mt-5">
      <div className="overflow-x-auto pb-2">
        <div className="min-w-max space-y-1.5">
          {rows.map((row) => (
            <div key={row.label} className="flex items-center gap-1.5">
              <span className="w-6 shrink-0 text-right text-xs text-ink-muted">
                {row.label}
              </span>
              {row.seats.map((seat) => {
                const isChosen = chosen.has(seat.id);
                const price = priceFor(seat.zone);
                const label = `${row.label}${seat.seat}${
                  price !== null ? ` · ${formatMoney(price, currency, locale)}` : ""
                }`;

                return (
                  <button
                    key={seat.id}
                    type="button"
                    disabled={busy || (!seat.available && !isChosen)}
                    onClick={() => onToggle(seat)}
                    title={label}
                    aria-label={label}
                    aria-pressed={isChosen}
                    className={[
                      "size-7 shrink-0 rounded text-[10px] font-medium tabular-nums transition-colors",
                      isChosen
                        ? "bg-brand text-brand-contrast"
                        : seat.available
                          ? "bg-emerald-100 text-emerald-900 hover:bg-emerald-200"
                          : "cursor-not-allowed bg-neutral-200 text-neutral-400",
                    ].join(" ")}
                  >
                    {seat.seat}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-xs text-ink-muted">
        <li className="flex items-center gap-1.5">
          <span className="size-3 rounded bg-emerald-100" aria-hidden />
          {labels.available}
        </li>
        <li className="flex items-center gap-1.5">
          <span className="size-3 rounded bg-brand" aria-hidden />
          {labels.selected}
        </li>
        {/* One grey for everything unavailable. The reason is the club's
            business, and the API does not tell us either. */}
        <li className="flex items-center gap-1.5">
          <span className="size-3 rounded bg-neutral-200" aria-hidden />
          {labels.unavailable}
        </li>
      </ul>
    </div>
  );
}

function GeneralAdmission({
  labels,
  available,
  quantity,
  onQuantity,
  onPick,
  busy,
}: {
  labels: TicketLabels;
  available: number;
  quantity: number;
  onQuantity: (value: number) => void;
  onPick: () => void;
  busy: boolean;
}) {
  return (
    <div className="mt-6 rounded-xl border border-rule bg-page p-5">
      <p className="text-sm">{labels.generalAdmission}</p>
      <p className="mt-1 text-xs text-ink-muted">
        {available} {labels.seatsLeft}
      </p>

      <div className="mt-4 flex items-center gap-3">
        <label className="text-sm" htmlFor="ga-quantity">
          {labels.howMany}
        </label>
        <input
          id="ga-quantity"
          type="number"
          min={1}
          max={Math.max(1, Math.min(available, 20))}
          value={quantity}
          onChange={(e) => onQuantity(Math.max(1, Number(e.target.value) || 1))}
          className="w-20 rounded-lg border border-rule px-3 py-2 text-sm tabular-nums"
        />
        <button
          type="button"
          disabled={busy || available === 0}
          onClick={onPick}
          className="rounded-full bg-brand px-5 py-2.5 text-sm font-medium text-brand-contrast disabled:opacity-50"
        >
          {labels.bestAvailable}
        </button>
      </div>
    </div>
  );
}
