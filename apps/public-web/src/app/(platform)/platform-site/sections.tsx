import type { ReactNode } from "react";

/**
 * Shared landing-page content.
 *
 * Plans are read from the API — the same plan catalogue the product bills on,
 * not a hand-maintained copy. A pricing page that disagrees with what a
 * customer is actually charged is worse than no pricing page.
 */

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

export function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M3 8.5 6.2 11.7 13 5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      {children}
    </svg>
  );
}

const stroke = {
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const MODULES: { title: string; body: string; icon: ReactNode }[] = [
  {
    title: "The club website",
    body: "Four designs, your colours and your crest. News, squads, fixtures, the league table, the club's honours and a footer you fill in yourself. Live on the first day, on your own address.",
    icon: (
      <Icon>
        <rect x="3" y="4" width="18" height="16" rx="2" {...stroke} />
        <path d="M3 9h18M8 4v5" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "Squads and players",
    body: "One player record with registrations, shirt numbers, positions and photographs. A coach sees their own team and nobody sees more than they should. Coaching staff are named and shown on the site.",
    icon: (
      <Icon>
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" {...stroke} />
        <circle cx="9" cy="7" r="4" {...stroke} />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "Matchday",
    body: "Competitions, fixtures, results and the league table. Connect a league feed and the calendar, scorers, cards and standings fill themselves in — or type them by hand, the way Liga 4 does.",
    icon: (
      <Icon>
        <circle cx="12" cy="12" r="9" {...stroke} />
        <path d="M12 7.5 15.5 10l-1.3 4.1H9.8L8.5 10 12 7.5Z" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "The club shop",
    body: "Shirts, scarves and programmes with sizes and stock, a basket that survives a reload, and orders paid at the counter when the supporter collects. No card processing to set up.",
    icon: (
      <Icon>
        <path d="M6 2 4 6v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6l-2-4H6Z" {...stroke} />
        <path d="M4 6h16M16 10a4 4 0 0 1-8 0" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "Supporters and email",
    body: "Supporter accounts with their order history, a newsletter list with consent recorded, and campaigns written in the same editor as your news. One-click unsubscribe, always.",
    icon: (
      <Icon>
        <rect x="2" y="4" width="20" height="16" rx="2" {...stroke} />
        <path d="m2 7 10 6 10-6" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "Who reads it",
    body: "Visitors, where they came from, what they read, and how many went on to buy — counted without cookies, so there is no consent banner to put in front of your own supporters.",
    icon: (
      <Icon>
        <path d="M3 3v18h18" {...stroke} />
        <path d="M7 15l3.5-4 3 2.5L20 7" {...stroke} />
      </Icon>
    ),
  },
];

interface PlanPrice {
  currency: string;
  amount_monthly: number | null;
  amount_yearly: number | null;
}

interface PublicPlan {
  key: string;
  name: string;
  tier: string;
  highlights: string[];
  prices: PlanPrice[];
}

function formatPrice(price: PlanPrice | undefined): { amount: string; period: string } {
  if (!price?.amount_monthly) return { amount: "Talk to us", period: "" };
  const value = price.amount_monthly / 100;
  const symbol = price.currency === "EUR" ? "€" : `${price.currency} `;
  return { amount: `${symbol}${value.toLocaleString()}`, period: "/month" };
}

async function fetchPlans(): Promise<PublicPlan[]> {
  try {
    const response = await fetch(`${API}/api/v1/public/plans`, {
      // Pricing changes rarely, and a stale page for an hour is far better than
      // a pricing page that fails to render because the API is restarting.
      next: { revalidate: 3600 },
    });
    if (!response.ok) return [];
    return (await response.json()) as PublicPlan[];
  } catch {
    return [];
  }
}

export async function Plans() {
  const plans = await fetchPlans();

  if (plans.length === 0) {
    return (
      <p className="m-lead" style={{ marginTop: "2rem" }}>
        Pricing is available on request while we finish onboarding our first clubs.{" "}
        <a href="/signup">Get in touch</a>.
      </p>
    );
  }

  return (
    <div className="m-plans">
      {plans.map((plan) => {
        const price = formatPrice(plan.prices.find((p) => p.currency === "EUR"));
        return (
          <article className="m-plan" key={plan.key} data-featured={plan.tier === "CLUB"}>
            <span className="m-plan-name">{plan.name}</span>
            <p className="m-price">
              {price.amount}
              {price.period && <span>{price.period}</span>}
            </p>
            <ul>
              {plan.highlights.map((line) => (
                <li key={line}>
                  <Check />
                  {line}
                </li>
              ))}
            </ul>
            <a className="m-btn m-btn-outline" href="/signup">
              Get started
            </a>
          </article>
        );
      })}
    </div>
  );
}
