import type { Metadata } from "next";

import { Plans } from "../sections";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Plans for clubs and academies. Every plan includes the club website, your "
    + "own domain and the newsroom.",
};

const COMPARISON: [string, string][] = [
  ["Club website and your own domain", "Every plan"],
  ["Newsroom, in every language you publish", "Every plan"],
  ["Squads, players and registrations", "Every plan"],
  ["Academy, training and attendance", "Every plan"],
  ["Ticketing and season tickets", "Club and above"],
  ["Membership, shop and fundraising", "Club and above"],
  ["Writing assistant", "Club and above"],
  ["Medical, scouting and load planning", "Pro and above"],
  ["Several clubs under one organisation", "Pro and above"],
  ["Single sign-on and API access", "Enterprise"],
];

export default function PricingPage() {
  return (
    <>
      <section className="m-hero" style={{ paddingBottom: "2rem" }}>
        <div className="m-shell">
          <span className="m-eyebrow">Pricing</span>
          <h1>Priced for clubs, not for enterprises.</h1>
          <p className="m-lead">
            Pick the plan that matches what your club actually does today. Moving up
            takes effect immediately and nothing has to be migrated.
          </p>
        </div>
      </section>

      <section className="m-section" style={{ borderTop: "none", paddingTop: 0 }}>
        <div className="m-shell">
          <Plans />
        </div>
      </section>

      <section className="m-section">
        <div className="m-shell">
          <h2>What is in which plan</h2>
          <div className="m-faq" style={{ marginTop: "2rem" }}>
            {COMPARISON.map(([feature, availability]) => (
              <div
                key={feature}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "1.5rem",
                  padding: "1rem 1.5rem",
                  background: "var(--panel)",
                }}
              >
                <span>{feature}</span>
                <span style={{ color: "var(--ink-muted)", whiteSpace: "nowrap" }}>
                  {availability}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="m-section">
        <div className="m-shell">
          <div className="m-cta">
            <h2>Not sure which one?</h2>
            <p className="m-lead">
              Start on the smallest plan that covers what you do this season. You can
              move up at any time, and nothing has to be set up again.
            </p>
            <a
              className="m-btn m-btn-primary m-btn-lg"
              href="/signup"
              style={{ marginTop: "2rem" }}
            >
              Get started
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
