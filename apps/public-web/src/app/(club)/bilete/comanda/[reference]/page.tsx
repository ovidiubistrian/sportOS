import { headers } from "next/headers";
import { notFound } from "next/navigation";
import QRCode from "qrcode";

import { formatMoney } from "@/lib/money";
import { preferredLocale, siteTranslator } from "@/lib/i18n";
import { getSite } from "@/lib/site";

/**
 * The tickets themselves.
 *
 * Rendered server-side and never cached: it carries live QR credentials, and a
 * CDN holding a copy of somebody's tickets is a copy of somebody's tickets.
 *
 * The QR is drawn to an SVG data URI on the server. No client-side library, no
 * canvas, and — more to the point — the credential never has to be handed to a
 * script running on the page. Printing works, and so does a screenshot, which
 * is what most supporters will actually do.
 *
 * The seat is printed *beside* the code, never inside it. What the QR carries
 * is an opaque reference and a signature and nothing else, so a ticket
 * photographed and posted online reveals nothing about who holds it.
 */
export const dynamic = "force-dynamic";

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

interface TicketView {
  ticket_number: string;
  ticket_type: string;
  holder_name: string | null;
  price_minor: number;
  currency: string;
  stand: string | null;
  section: string | null;
  row: string | null;
  seat: string | null;
  gate: string | null;
  qr: string | null;
}

interface OrderView {
  reference: string;
  status: string;
  total_minor: number;
  currency: string;
  buyer_name: string;
  tickets: TicketView[];
}

async function getOrder(reference: string): Promise<OrderView | null> {
  const incoming = await headers();
  const response = await fetch(
    `${API}/api/v1/public/tickets/orders/${encodeURIComponent(reference)}`,
    {
      headers: {
        "X-Forwarded-Host":
          incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "",
      },
      cache: "no-store",
    },
  );
  if (!response.ok) return null;
  return (await response.json()) as OrderView;
}

export default async function OrderPage({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const { reference } = await params;
  const site = await getSite();
  if (!site) notFound();

  const [order, i18n, locale] = await Promise.all([
    getOrder(reference),
    siteTranslator(site),
    preferredLocale(site),
  ]);
  if (!order) notFound();

  const codes = await Promise.all(
    order.tickets.map((ticket) =>
      ticket.qr
        ? QRCode.toString(ticket.qr, {
            type: "svg",
            margin: 0,
            errorCorrectionLevel: "M",
          })
        : Promise.resolve(null),
    ),
  );

  return (
    <div className="mx-auto max-w-2xl px-6 py-14">
      <p className="text-xs uppercase tracking-[0.22em] text-ink-muted">
        {i18n.t("publicSite", "orderPlaced")}
      </p>
      <h1 className="mt-2 font-mono text-3xl tracking-wider">{order.reference}</h1>
      <p className="mt-2 text-sm text-ink-muted">
        {order.buyer_name} · {formatMoney(order.total_minor, order.currency, locale)}
      </p>

      <div className="mt-10 space-y-5">
        {order.tickets.map((ticket, index) => (
          <article
            key={ticket.ticket_number}
            className="flex flex-wrap items-center gap-6 rounded-2xl border border-rule bg-page p-5 print:break-inside-avoid"
          >
            {codes[index] && (
              <div
                className="size-32 shrink-0 [&>svg]:h-full [&>svg]:w-full"
                aria-hidden
                dangerouslySetInnerHTML={{ __html: codes[index] as string }}
              />
            )}

            <div className="min-w-0 flex-1">
              <p className="text-lg font-semibold">
                {ticket.stand}
                {ticket.section ? ` · ${ticket.section}` : ""}
              </p>
              {(ticket.row || ticket.seat) && (
                <p className="mt-0.5 text-sm">
                  {i18n.t("publicSite", "ticketsRowSeat")} {ticket.row}
                  {ticket.seat}
                </p>
              )}
              <p className="mt-2 text-sm text-ink-muted">
                {ticket.ticket_type} ·{" "}
                {formatMoney(ticket.price_minor, ticket.currency, locale)}
              </p>
              {ticket.gate && (
                <p className="mt-2 text-sm">
                  <span className="text-ink-muted">
                    {i18n.t("publicSite", "ticketsGate")}
                  </span>{" "}
                  <span className="font-medium">{ticket.gate}</span>
                </p>
              )}
              <p className="mt-2 font-mono text-xs text-ink-faint">
                {ticket.ticket_number}
              </p>
            </div>
          </article>
        ))}
      </div>

      <p className="mt-8 text-sm text-ink-muted">
        {i18n.t("publicSite", "ticketsKeepSafe")}
      </p>
    </div>
  );
}
