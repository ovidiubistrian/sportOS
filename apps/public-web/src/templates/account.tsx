"use client";

import { useState, useTransition } from "react";

import type { Supporter } from "@/lib/supporter";

/**
 * The bits of the account page that change under the reader's hands.
 *
 * Kept deliberately small: the page itself is server-rendered, and only the
 * form and the two buttons are client components. A supporter reading their
 * order history should not be waiting on JavaScript to see it.
 */

export interface AccountLabels {
  name: string;
  phone: string;
  email: string;
  save: string;
  saving: string;
  saved: string;
  failed: string;
  marketing: string;
  marketingHint: string;
}

export interface ActionLabels {
  signOut: string;
  closeAccount: string;
  closeAccountHint: string;
  closeAccountConfirm: string;
}

export function AccountForm({
  supporter,
  labels,
}: {
  supporter: Supporter;
  labels: AccountLabels;
}) {
  const [name, setName] = useState(supporter.display_name);
  const [phone, setPhone] = useState(supporter.phone ?? "");
  const [marketing, setMarketing] = useState(supporter.marketing_opt_in);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "failed">("idle");

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setStatus("saving");
    const response = await fetch("/api/account", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: name.trim(),
        phone: phone.trim() || null,
        marketing_opt_in: marketing,
      }),
    });
    setStatus(response.ok ? "saved" : "failed");
  }

  return (
    <form onSubmit={save} className="grid gap-5 sm:max-w-md">
      <label className="grid gap-1.5">
        <span className="text-xs font-semibold tracking-wide text-ink-muted uppercase">
          {labels.name}
        </span>
        <input
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            setStatus("idle");
          }}
          required
          minLength={2}
          maxLength={160}
          className="rounded-lg border border-rule bg-page px-3.5 py-2.5 text-sm outline-none focus:border-[var(--brand)]"
        />
      </label>

      <label className="grid gap-1.5">
        <span className="text-xs font-semibold tracking-wide text-ink-muted uppercase">
          {labels.phone}
        </span>
        <input
          value={phone}
          onChange={(event) => {
            setPhone(event.target.value);
            setStatus("idle");
          }}
          inputMode="tel"
          maxLength={32}
          className="rounded-lg border border-rule bg-page px-3.5 py-2.5 text-sm outline-none focus:border-[var(--brand)]"
        />
      </label>

      {/* The email is the login's, and changing it here would only make this
          club's copy disagree with the account it came from. */}
      <div className="grid gap-1.5">
        <span className="text-xs font-semibold tracking-wide text-ink-muted uppercase">
          {labels.email}
        </span>
        <p className="rounded-lg border border-rule px-3.5 py-2.5 text-sm text-ink-muted">
          {supporter.email ?? "—"}
        </p>
      </div>

      <label className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={marketing}
          onChange={(event) => {
            setMarketing(event.target.checked);
            setStatus("idle");
          }}
          className="mt-0.5 h-4 w-4 accent-[var(--brand)]"
        />
        <span className="text-sm">
          {labels.marketing}
          <span className="mt-0.5 block text-xs text-ink-faint">{labels.marketingHint}</span>
        </span>
      </label>

      <div className="flex items-center gap-4">
        <button
          type="submit"
          disabled={status === "saving"}
          className="rounded-full px-5 py-2.5 text-sm font-semibold disabled:opacity-60"
          style={{ background: "var(--brand)", color: "var(--brand-contrast)" }}
        >
          {status === "saving" ? labels.saving : labels.save}
        </button>
        {status === "saved" && <span className="text-sm text-ink-muted">{labels.saved}</span>}
        {status === "failed" && <span className="text-sm text-danger">{labels.failed}</span>}
      </div>
    </form>
  );
}

export function AccountActions({ labels }: { labels: ActionLabels }) {
  const [pending, startTransition] = useTransition();

  function close() {
    // A browser confirm rather than a modal: this is the one destructive thing
    // on the club's public site, and the native dialog is the one every
    // supporter already knows how to read.
    if (!window.confirm(labels.closeAccountConfirm)) return;
    startTransition(async () => {
      await fetch("/api/account", { method: "DELETE" });
      window.location.href = "/";
    });
  }

  return (
    <div className="flex flex-col gap-6 border-t border-rule pt-8 sm:flex-row sm:items-start sm:justify-between">
      <form method="post" action="/api/auth/signout">
        <button type="submit" className="text-sm font-semibold text-brand-text hover:underline">
          {labels.signOut}
        </button>
      </form>

      <div className="sm:max-w-sm sm:text-right">
        <button
          type="button"
          onClick={close}
          disabled={pending}
          className="text-sm font-semibold text-danger hover:underline disabled:opacity-60"
        >
          {labels.closeAccount}
        </button>
        <p className="mt-1.5 text-xs text-ink-faint">{labels.closeAccountHint}</p>
      </div>
    </div>
  );
}
