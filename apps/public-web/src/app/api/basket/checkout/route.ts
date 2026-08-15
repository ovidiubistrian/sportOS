import { cookies, headers } from "next/headers";
import { NextResponse } from "next/server";

import { ACCESS_COOKIE } from "@/lib/auth";

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";
const COOKIE = "footbola_cart";

/** Place the order, then drop the cookie: that basket is spent. */
export async function POST(request: Request) {
  const incoming = await headers();
  const jar = await cookies();
  const token = jar.get(COOKIE)?.value;
  // Passed on when there is one, so the order lands in the buyer's account.
  // Absent for a guest, which the API accepts — a shop that demands an account
  // before it will take money is a shop that takes less money.
  const session = jar.get(ACCESS_COOKIE)?.value;

  const response = await fetch(`${API}/api/v1/public/basket/checkout`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Forwarded-Host": incoming.get("x-forwarded-host") ?? incoming.get("host") ?? "",
      ...(token ? { "X-Cart-Token": token } : {}),
      ...(session ? { Authorization: `Bearer ${session}` } : {}),
    },
    body: JSON.stringify(await request.json()),
    cache: "no-store",
  });

  const body = await response.json().catch(() => ({}));
  if (response.ok) {
    // Keeping it would show the buyer an empty basket they cannot check out
    // and a 404 if they tried — the cart is converted, not open.
    jar.delete(COOKIE);
  }
  return NextResponse.json(body, { status: response.status });
}
