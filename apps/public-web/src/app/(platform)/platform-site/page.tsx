import Link from "next/link";

import { MODULES, Plans } from "./sections";

/**
 * The landing page.
 *
 * Written for the person who actually buys this: someone running a club on
 * three spreadsheets, a WhatsApp group and a website nobody has updated since
 * 2019. So it leads with the work, not with the technology — no architecture
 * diagrams, no "AI-powered", and every claim is something the product does
 * today.
 */

const FAQ = [
  {
    q: "Is this only for football?",
    a: "No. Football, futsal, handball, basketball, volleyball, rugby, ice hockey and water polo — each with its own points rules, positions and match events, because two points for a handball win and three for a football one is not a detail. A club running three sports runs them in one account.",
  },
  {
    q: "Do we need someone technical?",
    a: "No. A club sets up its website by picking a template and up to three colours; everything else is filling in what you already know — teams, players, fixtures. There is nothing to install and nothing to host.",
  },
  {
    q: "Can we use our own domain?",
    a: "Yes. Point your domain at us and the certificate is issued automatically on the first visit. Until then your site is live on a teamsport360.com address, so you are never waiting on DNS to get started.",
  },
  {
    q: "Who can see medical and safeguarding records?",
    a: "Only the people you give that permission to. Medical data sits behind its own permission, never appears on a player profile, and is deliberately excluded from the audit trail's field list — the fact of access is recorded, the content is not.",
  },
  {
    q: "What happens to our data if we leave?",
    a: "You export it and we delete it. Everything a club owns is scoped to that club in the database, so an export is a complete copy and an erasure is complete too.",
  },
  {
    q: "Is our data separate from other clubs'?",
    a: "Yes, and at four layers: the request context, the data layer, the database's own row-level security, and the foreign keys themselves. The application's database role cannot bypass those policies even if the application has a bug.",
  },
];

export default function LandingPage() {
  return (
    <>
      <section className="m-hero">
        <div className="m-shell">
          <span className="m-eyebrow">For clubs and academies</span>
          <h1>Everything your club does, in one place.</h1>
          <p className="m-lead">
            The website, the squads, the fixtures, the shop and the supporters — one
            system instead of six spreadsheets and a group chat. Football, handball,
            basketball, volleyball and more, because a CSM is rarely one sport. Set
            up in an afternoon by whoever already does the admin.
          </p>
          <div className="m-hero-actions">
            <a className="m-btn m-btn-primary m-btn-lg" href="/signup">
              Get started
            </a>
            <Link className="m-btn m-btn-outline m-btn-lg" href="/pricing">
              See pricing
            </Link>
          </div>
          <p className="m-hero-note">
            No card to start. Your club website is live on the first day.
          </p>

          {/* Real screens, not an illustration of one. A club buying this wants
              to see what its own site will look like, and a mock-up is the one
              thing a landing page can show that the product cannot deliver. */}
          <figure className="m-shot">
            <img
              src="/product/club-site.jpg"
              alt="A club's home page: news, the next fixture and the league table."
              width={1503}
              height={812}
              loading="eager"
            />
            <figcaption>A club home page, in the club's own colours.</figcaption>
          </figure>
        </div>
      </section>

      <section className="m-section" id="modules">
        <div className="m-shell">
          <span className="m-eyebrow">What it does</span>
          <h2>Everything a club actually does, in one system</h2>
          <p className="m-lead">
            Not modules bolted together. One player record, one squad, one fixture —
            used by the coach, the registrar, the shop and the website at the same
            time.
          </p>

          <div className="m-grid">
            {MODULES.map((module) => (
              <article className="m-card" key={module.title}>
                <span className="m-icon" aria-hidden>
                  {module.icon}
                </span>
                <h3>{module.title}</h3>
                <p>{module.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="m-section" id="website">
        <div className="m-shell">
          <span className="m-eyebrow">Club website</span>
          <h2>A website your club is not embarrassed by</h2>
          <p className="m-lead">
            Pick one of four layouts and up to three colours. Squads, fixtures and
            news come from the same records your staff already keep, so the site is
            never out of date — because nobody has to remember to update it twice.
          </p>

          <div className="m-shots">
            <figure className="m-shot">
              <img
                src="/product/squads.jpg"
                alt="The squads page: every team, player counts and the head coach."
                width={1503}
                height={812}
                loading="lazy"
              />
              <figcaption>Squads, with the coach and the players' faces.</figcaption>
            </figure>
            <figure className="m-shot">
              <img
                src="/product/shop.jpg"
                alt="The club shop with sizes, stock and a basket."
                width={1503}
                height={812}
                loading="lazy"
              />
              <figcaption>The club shop — sizes, stock, pay on collection.</figcaption>
            </figure>
          </div>

          <dl className="m-stats">
            <div className="m-stat">
              <dt>Layouts</dt>
              <dd>4</dd>
            </div>
            <div className="m-stat">
              <dt>Sports supported</dt>
              <dd>8</dd>
            </div>
            <div className="m-stat">
              <dt>Languages per article</dt>
              <dd>Any</dd>
            </div>
            <div className="m-stat">
              <dt>Your own domain</dt>
              <dd>Included</dd>
            </div>
            <div className="m-stat">
              <dt>Time to publish a signing</dt>
              <dd>2 min</dd>
            </div>
          </dl>

          <div className="m-grid">
            <article className="m-card">
              <h3>Publish in every language you play in</h3>
              <p>
                One article, many translations, one lifecycle. A story can be live in
                Romanian while the German version is still being written — and the
                newsroom shows you exactly that.
              </p>
            </article>
            <article className="m-card">
              <h3>Templates for the things clubs write</h3>
              <p>
                A signing, a departure, a match report. Each one starts with the right
                structure instead of a blank page, and the writing assistant tightens
                your words without ever inventing a fact.
              </p>
            </article>
            <article className="m-card">
              <h3>Your colours, checked for legibility</h3>
              <p>
                Contrast is calculated when you pick a colour, and the site quietly
                uses a readable variant for text where it has to. A club's own colour
                should never make its own website unreadable.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section className="m-section" id="security">
        <div className="m-shell">
          <span className="m-eyebrow">Trust</span>
          <h2>Built for data that belongs to children</h2>
          <p className="m-lead">
            Most of what a football academy stores is personal data about minors. That
            shaped the architecture, not the marketing page.
          </p>

          <div className="m-grid">
            <article className="m-card">
              <h3>One club cannot see another</h3>
              <p>
                Isolation is enforced by the database itself, not only by application
                code. The runtime database role cannot bypass those policies — so a bug
                in a query returns nothing rather than someone else's players.
              </p>
            </article>
            <article className="m-card">
              <h3>Medical data is separate by design</h3>
              <p>
                Coaching staff see availability, never a diagnosis. Clinical detail
                sits behind its own permission and is excluded from the general audit
                trail on purpose.
              </p>
            </article>
            <article className="m-card">
              <h3>Every change has an author</h3>
              <p>
                Who changed what, when, and from which request. Only fields on an
                explicit allow-list are ever recorded, so adding a column never starts
                leaking it.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section className="m-section" id="pricing">
        <div className="m-shell">
          <span className="m-eyebrow">Pricing</span>
          <h2>Priced for clubs, not for enterprises</h2>
          <p className="m-lead">
            Every plan includes the club website, your own domain and unlimited staff
            accounts on the tiers that need them. No per-seat surprises.
          </p>
          <Plans />
        </div>
      </section>

      <section className="m-section" id="faq">
        <div className="m-shell">
          <span className="m-eyebrow">Questions</span>
          <h2>The things clubs ask first</h2>

          <div className="m-faq">
            {FAQ.map((item) => (
              <details key={item.q}>
                <summary>{item.q}</summary>
                <p>{item.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="m-section">
        <div className="m-shell">
          <div className="m-cta">
            <h2>Start with your squad list</h2>
            <p className="m-lead">
              Add your teams and players, pick your colours, and your club has a
              website by the end of the afternoon.
            </p>
            <div
              style={{
                display: "flex",
                gap: "0.75rem",
                justifyContent: "center",
                marginTop: "2rem",
                flexWrap: "wrap",
              }}
            >
              <a className="m-btn m-btn-primary m-btn-lg" href="/signup">
                Get started
              </a>
              <Link className="m-btn m-btn-outline m-btn-lg" href="/pricing">
                Compare plans
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
