import Link from "next/link";

/**
 * Header and footer for the platform site.
 *
 * "Sign in" points at `/signin`, which the proxy routes to the admin
 * application on this same host. That is what makes the whole product live at
 * one address: a club owner types "footbola", reads what it does, signs in, and
 * lands in their own club — without ever learning a second hostname.
 */

const SIGN_IN = "/signin";
const SIGN_UP = "/signup";

export function Header() {
  return (
    <header className="m-header">
      <div className="m-shell m-header-inner">
        <Link href="/" className="m-logo">
          <span className="m-mark" aria-hidden>
            TS360
          </span>
          TeamSport360
        </Link>

        <nav className="m-nav" aria-label="Main">
          <Link href="/#modules">What it does</Link>
          <Link href="/#website">Club website</Link>
          <Link href="/pricing">Pricing</Link>
          <Link href="/#faq">FAQ</Link>
        </nav>

        <div className="m-header-actions">
          <a className="m-btn m-btn-ghost" href={SIGN_IN}>
            Sign in
          </a>
          <a className="m-btn m-btn-primary" href={SIGN_UP}>
            Get started
          </a>
        </div>
      </div>
    </header>
  );
}

export function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="m-footer">
      <div className="m-shell">
        <div className="m-footer-cols">
          <div>
            <Link href="/" className="m-logo">
              <span className="m-mark" aria-hidden>
                TS360
              </span>
              TeamSport360
            </Link>
            <p style={{ marginTop: "0.875rem", maxWidth: "22rem" }}>
              One system for the club, the academy, the matchday and the website.
            </p>
          </div>

          <div>
            <h4>Product</h4>
            <ul>
              <li>
                <Link href="/#modules">Modules</Link>
              </li>
              <li>
                <Link href="/#website">Club website</Link>
              </li>
              <li>
                <Link href="/pricing">Pricing</Link>
              </li>
            </ul>
          </div>

          <div>
            <h4>Trust</h4>
            <ul>
              <li>
                <Link href="/#security">Security</Link>
              </li>
              <li>
                <Link href="/#faq">Data &amp; privacy</Link>
              </li>
            </ul>
          </div>

          <div>
            <h4>Account</h4>
            <ul>
              <li>
                <a href={SIGN_IN}>Sign in</a>
              </li>
              <li>
                <a href={SIGN_UP}>Get started</a>
              </li>
            </ul>
          </div>
        </div>

        <div className="m-footer-base">
          <span>© {year} TeamSport360</span>
          <span>Built for clubs, not for enterprises.</span>
        </div>
      </div>
    </footer>
  );
}
