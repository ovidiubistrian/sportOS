"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * Counts a page view, once per navigation.
 *
 * No cookie, no identifier, nothing stored in the browser — the server derives
 * a daily visitor hash from headers it already has. This component's whole job
 * is to say "somebody looked at this path", which is why it sends the path and
 * the referrer and nothing else.
 *
 * `sendBeacon` where the browser has it: it survives the page being closed,
 * which is exactly when the last view of a session happens.
 */

function send(payload: Record<string, unknown>) {
  const body = JSON.stringify(payload);
  if (typeof navigator !== "undefined" && navigator.sendBeacon) {
    navigator.sendBeacon("/api/track", new Blob([body], { type: "application/json" }));
    return;
  }
  void fetch("/api/track", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {
    // A missed measurement is not worth an error in a supporter's console.
  });
}

/**
 * Report something that is not a page view.
 *
 * Exported so the shop and the newsletter can say what happened without each
 * of them rebuilding the beacon. Fire-and-forget by design: a measurement must
 * never delay the thing it is measuring, and a failed one is not worth telling
 * a supporter about.
 */
export function track(kind: string, extra: Record<string, unknown> = {}) {
  send({ kind, path: window.location.pathname, referrer: null, ...extra });
}

export function Beacon({ kind = "PAGEVIEW", locale }: { kind?: string; locale?: string }) {
  const pathname = usePathname();
  const params = useSearchParams();
  // Guards React's double-invoked effects in development, and a re-render that
  // does not change the path.
  const lastSent = useRef<string | null>(null);

  useEffect(() => {
    const key = `${kind}:${pathname}`;
    if (lastSent.current === key) return;
    lastSent.current = key;

    send({
      kind,
      path: pathname,
      // The full referrer goes no further than the API, which keeps only its
      // host — a search URL carries what somebody typed.
      referrer: document.referrer || null,
      utm_source: params.get("utm_source"),
      utm_medium: params.get("utm_medium"),
      utm_campaign: params.get("utm_campaign"),
      locale,
    });
  }, [kind, pathname, params, locale]);

  return null;
}
