"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

/**
 * The navigation on a phone.
 *
 * The header used to render one flex row of links at every width. Five of
 * them, a crest and an account button do not fit across 390 points, so the row
 * pushed the page wider than the screen — and because the overflow was on the
 * body, everything moved when a supporter scrolled sideways, including the
 * header itself. The league table looked broken as a result, when in fact it
 * had been scrolling in its own container correctly all along.
 *
 * A client island, and the only one in the shell: the links themselves stay in
 * the server-rendered header for a reader who never opens this, and for the
 * crawler that never will. Labels arrive resolved because this cannot reach the
 * translator, which reads request headers.
 */

export interface NavItem {
  href: string;
  label: string;
}

export function MobileNav({
  items,
  openLabel,
  closeLabel,
}: {
  items: NavItem[];
  openLabel: string;
  closeLabel: string;
}) {
  const [open, setOpen] = useState(false);

  // A phone rotated to landscape crosses the breakpoint that hides this button
  // entirely, which would otherwise leave the panel open and unclosable.
  useEffect(() => {
    if (!open) return;
    const media = window.matchMedia("(min-width: 768px)");
    const close = () => setOpen(false);
    media.addEventListener("change", close);
    return () => media.removeEventListener("change", close);
  }, [open]);

  // The page behind must not scroll while the panel is over it.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="md:hidden">
      <button
        type="button"
        aria-label={open ? closeLabel : openLabel}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        // 44 points square: the smallest target a thumb hits reliably.
        className="-mr-2 grid size-11 place-items-center rounded-md text-ink"
      >
        <svg
          viewBox="0 0 24 24"
          className="size-6"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          aria-hidden
        >
          {open ? (
            <path d="M6 6l12 12M18 6L6 18" />
          ) : (
            <>
              <path d="M4 7h16" />
              <path d="M4 12h16" />
              <path d="M4 17h16" />
            </>
          )}
        </svg>
      </button>

      {open && (
        <div className="fixed inset-x-0 top-16 bottom-0 z-30 overflow-y-auto bg-page">
          <nav aria-label="Main">
            <ul className="flex flex-col px-6 py-2">
              {items.map((item) => (
                <li key={item.href} className="border-b border-rule last:border-0">
                  <Link
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className="block py-4 text-base font-medium text-ink"
                  >
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      )}
    </div>
  );
}
