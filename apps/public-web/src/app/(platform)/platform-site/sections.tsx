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
    title: "Squads and players",
    body: "One player record with registrations, shirt numbers, documents and guardians. A coach sees their own team; nobody sees more than they should.",
    icon: (
      <Icon>
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" {...stroke} />
        <circle cx="9" cy="7" r="4" {...stroke} />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "Academy and training",
    body: "Age groups, registrations, session plans and attendance. The register is taken on a phone at the side of the pitch, not typed up on Sunday night.",
    icon: (
      <Icon>
        <path d="M3 7l9-4 9 4-9 4-9-4Z" {...stroke} />
        <path d="M7 10v5c0 1.7 2.2 3 5 3s5-1.3 5-3v-5" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "Matchday",
    body: "Fixtures, squads, results and minutes played. Everything the website needs to be right on Sunday evening without anyone copying it across.",
    icon: (
      <Icon>
        <circle cx="12" cy="12" r="9" {...stroke} />
        <path d="M12 7.5 15.5 10l-1.3 4h-4.4L8.5 10 12 7.5Z" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "Club website",
    body: "Four layouts, your colours, your domain. Squads and fixtures come from the same records your staff already keep, so the site cannot drift out of date.",
    icon: (
      <Icon>
        <circle cx="12" cy="12" r="9" {...stroke} />
        <path d="M3 12h18M12 3c2.5 2.7 3.8 5.8 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.8-3.8-9S9.5 5.7 12 3Z" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "Newsroom",
    body: "Match reports, signings and farewells — each starting from the right structure. Publish in every language your club plays in, from one article.",
    icon: (
      <Icon>
        <path d="M4 5h11a2 2 0 0 1 2 2v12H6a2 2 0 0 1-2-2V5Z" {...stroke} />
        <path d="M17 9h3v8a2 2 0 0 1-2 2M8 9h5M8 13h5" {...stroke} />
      </Icon>
    ),
  },
  {
    title: "Members and money",
    body: "Membership, academy fees and matchday income against one fan record — so the club knows who supports it and how, in one place.",
    icon: (
      <Icon>
        <rect x="2.5" y="6" width="19" height="12" rx="2.5" {...stroke} />
        <path d="M2.5 10h19" {...stroke} />
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
