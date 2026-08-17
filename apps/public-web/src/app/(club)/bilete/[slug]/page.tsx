import { notFound } from "next/navigation";

import { preferredLocale, siteTranslator } from "@/lib/i18n";
import { getSite, getTicketedEvent } from "@/lib/site";
import { TicketPicker } from "@/templates/tickets";

/**
 * Rendered per request, never cached.
 *
 * Availability is the entire point of the page. A supporter choosing from a
 * map that is thirty seconds old is a supporter told a seat is free and then
 * refused it at checkout, which is the one experience this module exists to
 * avoid.
 */
export const dynamic = "force-dynamic";

export default async function TicketEventPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const site = await getSite();
  if (!site) notFound();

  const [event, i18n, locale] = await Promise.all([
    getTicketedEvent(slug),
    siteTranslator(site),
    preferredLocale(site),
  ]);
  if (!event) notFound();

  const when = new Intl.DateTimeFormat(locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <a
        href="/bilete"
        className="text-sm text-ink-muted underline-offset-4 hover:underline"
      >
        ← {i18n.t("publicSite", "ticketsTitle")}
      </a>

      <h1 className="mt-3 text-3xl font-semibold tracking-tight">{event.name}</h1>
      <p className="mt-1 text-sm text-ink-muted">
        {when.format(new Date(event.kickoff_at))} · {event.layout.venue.name}
      </p>

      <div className="mt-10">
        <TicketPicker
          event={event}
          locale={locale}
          labels={{
            chooseSector: i18n.t("publicSite", "ticketsChooseSector"),
            chooseSeats: i18n.t("publicSite", "ticketsChooseSeats"),
            back: i18n.t("publicSite", "ticketsBack"),
            available: i18n.t("publicSite", "ticketsAvailable"),
            unavailable: i18n.t("publicSite", "ticketsUnavailable"),
            selected: i18n.t("publicSite", "ticketsSelected"),
            soldOut: i18n.t("publicSite", "ticketsSoldOut"),
            from: i18n.t("publicSite", "ticketsFrom"),
            yourSeats: i18n.t("publicSite", "ticketsYourSeats"),
            noneChosen: i18n.t("publicSite", "ticketsNoneChosen"),
            bestAvailable: i18n.t("publicSite", "ticketsBestAvailable"),
            howMany: i18n.t("publicSite", "ticketsHowMany"),
            holdExpires: i18n.t("publicSite", "ticketsHoldExpires"),
            holdExpired: i18n.t("publicSite", "ticketsHoldExpired"),
            total: i18n.t("publicSite", "total"),
            yourName: i18n.t("publicSite", "yourName"),
            email: i18n.t("publicSite", "email"),
            phone: i18n.t("publicSite", "phone"),
            payAtCounter: i18n.t("publicSite", "payOnCollection"),
            payByCard: i18n.t("publicSite", "payByCard"),
            cardSafe: i18n.t("publicSite", "cardSafe"),
            buy: i18n.t("publicSite", "ticketsBuy"),
            orderPlaced: i18n.t("publicSite", "orderPlaced"),
            orderReference: i18n.t("publicSite", "orderReference"),
            showTickets: i18n.t("publicSite", "ticketsShow"),
            generalAdmission: i18n.t("publicSite", "ticketsGeneralAdmission"),
            seatsLeft: i18n.t("publicSite", "ticketsSeatsLeft"),
            remove: i18n.t("publicSite", "remove"),
            standing: i18n.t("publicSite", "ticketsStanding"),
          }}
        />
      </div>
    </div>
  );
}
