import { notFound } from "next/navigation";

import { preferredLocale, siteTranslator } from "@/lib/i18n";
import { getSite, getTicketedEvents } from "@/lib/site";
import { EmptyState } from "@/templates/shared";

export const metadata = { title: "Bilete" };

/**
 * Matches on sale.
 *
 * A list rather than a map: at this level the supporter is choosing a fixture,
 * not a seat, and the ground is the same one every time.
 */
export default async function TicketsPage() {
  const site = await getSite();
  if (!site) notFound();

  const [events, i18n, locale] = await Promise.all([
    getTicketedEvents(),
    siteTranslator(site),
    preferredLocale(site),
  ]);

  const when = new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="mx-auto max-w-4xl px-6 py-14">
      <span className="text-xs font-semibold tracking-[0.25em] uppercase text-ink-muted">
        {site.short_name} · {i18n.t("publicSite", "ticketsEyebrow")}
      </span>
      <h1 className="mt-3 text-4xl font-semibold tracking-tight">
        {i18n.t("publicSite", "ticketsTitle")}
      </h1>

      {events.length === 0 ? (
        <div className="mt-10">
          <EmptyState>{i18n.t("publicSite", "ticketsNone")}</EmptyState>
        </div>
      ) : (
        <ul className="mt-10 space-y-3">
          {events.map((event) => (
            <li key={event.slug}>
              <a
                href={`/bilete/${event.slug}`}
                className="flex flex-wrap items-center gap-4 rounded-2xl border border-rule bg-page p-5 transition-colors hover:border-brand"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-lg font-semibold">{event.name}</span>
                  <span className="mt-0.5 block text-sm text-ink-muted">
                    {when.format(new Date(event.kickoff_at))}
                    {event.competition_label ? ` · ${event.competition_label}` : ""}
                  </span>
                </span>
                <span className="text-sm text-ink-muted tabular-nums">
                  {event.available > 0
                    ? `${event.available} ${i18n.t("publicSite", "ticketsSeatsLeft")}`
                    : i18n.t("publicSite", "ticketsSoldOut")}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
