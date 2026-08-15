import type { ReactNode } from "react";

/**
 * The club site's section furniture.
 *
 * Lifted from the marketing site's visual language — a pill eyebrow, a large
 * tight headline, a quiet lead paragraph — because the two are the same product
 * and were reading as two. What is *not* lifted is the palette: the marketing
 * site is one dark theme with one blue, and a club site is whatever colour the
 * club picked, so every accent here resolves through `--brand`.
 *
 * One component rather than a class, so a change to the rhythm lands on every
 * section at once instead of on the four somebody remembers.
 */

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <span
      className="mb-4 inline-flex items-center gap-2 rounded-full border border-rule px-3 py-1.5 text-xs font-medium text-ink-muted"
      style={{ background: "color-mix(in srgb, var(--brand) 4%, transparent)" }}
    >
      {children}
    </span>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  lead,
  action,
}: {
  eyebrow?: ReactNode;
  title: string;
  lead?: string;
  /** Sits opposite the heading on a wide screen, under it on a phone. */
  action?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-2xl">
        {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
        <h2 className="font-display text-[clamp(1.75rem,3.5vw,2.5rem)] leading-[1.05] font-extrabold tracking-[-0.03em] text-balance">
          {title}
        </h2>
        {lead && <p className="mt-3 text-sm/relaxed text-ink-muted">{lead}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** The standard surface: hairline border, generous radius, no drop shadow. */
export const PANEL =
  "rounded-xl border border-rule bg-[color-mix(in_srgb,var(--brand)_3%,transparent)]";
