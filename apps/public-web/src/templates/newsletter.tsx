"use client";

import { useState } from "react";

import { track } from "./beacon";

/**
 * The newsletter sign-up, at the foot of the club's front page.
 *
 * Answers the same way whether the address was already on the list or has just
 * been added. A form that says "you are already subscribed" tells a stranger
 * who reads the club's newsletter, which is not the club's to give away.
 */

export interface NewsletterLabels {
  title: string;
  body: string;
  placeholder: string;
  submit: string;
  done: string;
  failed: string;
  consent: string;
}

export function Newsletter({ labels }: { labels: NewsletterLabels }) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "done" | "failed">("idle");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setState("sending");
    const response = await fetch("/api/newsletter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.trim() }),
    }).catch(() => null);
    setState(response?.ok ? "done" : "failed");
    if (response?.ok) {
      // A signup is the conversion the club's front page exists to produce, so
      // it is a funnel step and not only a page view.
      track("NEWSLETTER_SIGNUP");
    }
  }

  return (
    <section
      className="px-6 py-16"
      style={{ background: "color-mix(in srgb, var(--brand) 7%, transparent)" }}
    >
      <div className="mx-auto max-w-xl text-center">
        <h2 className="font-display text-[clamp(1.75rem,3.5vw,2.5rem)] leading-[1.05] font-extrabold tracking-[-0.03em] text-balance">
          {labels.title}
        </h2>
        <p className="mt-2 text-sm/relaxed text-ink-muted">{labels.body}</p>

        {state === "done" ? (
          <p
            className="mt-7 text-sm font-semibold"
            style={{ color: "var(--brand)" }}
            role="status"
          >
            {labels.done}
          </p>
        ) : (
          <form onSubmit={submit} className="mt-7 flex flex-col gap-3 sm:flex-row">
            <input
              type="email"
              required
              value={email}
              aria-label={labels.placeholder}
              placeholder={labels.placeholder}
              onChange={(event) => setEmail(event.target.value)}
              className="flex-1 rounded-full border border-rule bg-page px-5 py-3.5 text-sm outline-none transition-colors focus:border-[var(--brand)]"
            />
            <button
              type="submit"
              disabled={state === "sending"}
              className="rounded-full px-8 py-3.5 text-xs font-bold tracking-widest uppercase transition-transform duration-200 hover:-translate-y-0.5 disabled:opacity-50"
              style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
            >
              {labels.submit}
            </button>
          </form>
        )}

        {state === "failed" && (
          <p className="mt-3 text-xs font-medium text-[#b3352c]">{labels.failed}</p>
        )}

        <p className="mt-4 text-xs text-ink-faint">{labels.consent}</p>
      </div>
    </section>
  );
}
