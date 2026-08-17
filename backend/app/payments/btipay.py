"""BT iPay — Banca Transilvania's e-commerce gateway.

The gateway is RBS/Assist under BT's branding. REST, form-encoded requests,
JSON responses, HTTP Basic auth over TLS — no HMAC, no key pairs, no OAuth.
Credentials are issued per merchant once the processing contract is signed,
which is why they live per tenant in the database and never in the environment.

    register.do                 register a one-phase order, get the hosted URL
    registerPreAuth.do          the two-phase variant: hold now, capture later
    getOrderStatusExtended.do   what actually happened — the only source of truth
    deposit.do                  capture a held authorisation
    reverse.do                  release one, within a day, while still held
    refund.do                   return money on a captured order

**There is no webhook.** Any design that waits for the bank to call back is
wrong for this gateway. An order's outcome is learned by asking: once when the
buyer returns to the return URL, and again from reconciliation for the buyer
whose browser never came back.

Every rule enforced below about diacritics, field lengths, phone format and
empty address blocks is one the gateway enforces too — by refusing the
registration, usually with an error code that names the wrong field or, worse,
one that names something else entirely.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import httpx

from app.payments.base import (
    CheckoutSession,
    PaymentProvider,
    PaymentProviderError,
    SessionStatus,
)

log = logging.getLogger(__name__)

# ISO 4217 numeric, which is what the gateway wants — "RON" is refused.
_CURRENCY_NUMERIC = {"RON": "946", "EUR": "978", "USD": "840"}

# Romania, in the same numeric vocabulary, for the address blocks.
_COUNTRY_RO = "642"

# The gateway's own limits on the order bundle. Exceeding one is `errorCode 8`,
# which reports the field but only after the buyer has been sent nowhere.
_MAX_POST_ADDRESS = 50
_MAX_CITY = 40
_MAX_DESCRIPTION = 125


def strip_diacritics(text: str | None) -> str:
    """Fold a string to plain ASCII on one line.

    The gateway refuses an order bundle containing diacritics. It does not say
    so: the registration comes back `2003 — Non-3DS transaction forbidden for
    merchant`, which reads like a merchant configuration problem and sends you
    to the bank rather than to the address field. A Romanian club's addresses
    are full of ă, â, î, ș and ț, so this is the common case and not the edge.

    Decomposing to NFKD separates each base letter from its mark; dropping the
    combining marks leaves the letter. Newlines are refused as well, so runs of
    whitespace collapse to a single space.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    unmarked = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    # Anything still outside ASCII — odd punctuation, a stray symbol — goes
    # too. The gateway wants plain, and half-plain is refused the same way.
    ascii_only = unmarked.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_only).strip()


def normalise_phone(raw: str | None, *, country_code: str = "40") -> str:
    """Digits only, international, without the plus or the double zero.

    A Romanian number as anybody writes it — `0740 123 456` — is refused. The
    trunk zero is replaced by the country code, giving `40740123456`. A number
    already in international form passes through; the gateway checks the length
    itself and will say so.
    """
    if not raw:
        return ""
    cleaned = re.sub(r"[^\d+]", "", str(raw))
    if not cleaned:
        return ""
    if cleaned.startswith("+"):
        return cleaned[1:]
    if cleaned.startswith("00"):
        return cleaned[2:]
    if cleaned.startswith("0"):
        return f"{country_code}{cleaned[1:]}"
    return cleaned


# The gateway's order states, from the integration guide. Several of them
# collapse to one word of ours, which is fine for deciding what to show a
# buyer and dangerous for deciding whether to cancel — see `SessionStatus.raw`
# and the reconciliation that reads the number rather than the word.
_ORDER_STATUS = {
    0: "pending",  # registered, nobody has tried to pay
    1: "approved",  # held, two-phase, not captured
    2: "completed",  # captured — the money has moved
    3: "failed",  # the hold was released
    4: "refunded",
    5: "pending",  # authentication in progress
    6: "failed",  # refused by the issuer
    7: "partially_refunded",
}

# The two states that mean "somebody is in the middle of paying". Neither may
# ever be cancelled from under them: 1 is money already held, 5 is a buyer on
# their bank's authentication screen. Both arrive here as "pending", which is
# also what 0 — nobody tried — arrives as, so the distinction cannot be made
# from the mapped word.
LIVE_ORDER_STATUSES = frozenset({1, 5})

PAID_ORDER_STATUS = 2


@dataclass(frozen=True, slots=True)
class IPayCredentials:
    user_name: str
    password: str
    sandbox: bool = True
    # Set only for aggregators registering on behalf of a sub-merchant.
    child_id: str | None = None

    @property
    def base_url(self) -> str:
        return (
            "https://ecclients-sandbox.btrl.ro" if self.sandbox else "https://ecclients.btrl.ro"
        )

    def auth_header(self) -> str:
        token = base64.b64encode(f"{self.user_name}:{self.password}".encode()).decode("ascii")
        return f"Basic {token}"


class BtIpayProvider(PaymentProvider):
    key = "btipay"
    display_name = "BT iPay"

    # Generous on purpose. The sandbox regularly takes twenty seconds to answer
    # a status call after authentication, and a timeout here does not mean "no
    # payment" — it means a paid order left sitting unpaid, which is the one
    # failure that costs a club money rather than a page load.
    _TIMEOUT = httpx.Timeout(45.0, connect=10.0)
    _ATTEMPTS = 2

    def __init__(
        self,
        *,
        user_name: str,
        password: str,
        sandbox: bool = True,
        child_id: str | None = None,
    ) -> None:
        user = (user_name or "").strip()
        secret = (password or "").strip()
        if not user or not secret:
            raise PaymentProviderError("BT iPay needs a user name and a password.")
        self.credentials = IPayCredentials(
            user_name=user,
            password=secret,
            sandbox=bool(sandbox),
            child_id=(child_id or None),
        )
        self._journal: Any = None

    def with_journal(self, journal: Any) -> BtIpayProvider:
        """Attach the audit journal every call writes to.

        Separate from construction because the settings screen tests
        credentials that have no order to write against, and because the
        journal needs a database session the constructor has no business
        holding. Returns self so it reads as one expression at the call site.
        """
        self._journal = journal
        return self

    # ----------------------------------------------------------------- wire

    async def _post(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """One form-encoded call, journaled whether it worked or not.

        Nested values are sent as compact JSON, which is how the gateway wants
        the order bundle. Booleans go as words. `None` is dropped rather than
        sent empty — an empty string is a value to this gateway, and usually
        an invalid one.
        """
        url = f"{self.credentials.base_url}{path}"
        form: dict[str, str] = {}
        for name, value in params.items():
            if value is None:
                continue
            if isinstance(value, dict | list):
                form[name] = json.dumps(value, separators=(",", ":"))
            elif isinstance(value, bool):
                form[name] = "true" if value else "false"
            else:
                form[name] = str(value)

        headers = {
            "Authorization": self.credentials.auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # What the wire saw, for the journal. The Authorization header is
        # redacted on the way into storage, not here — the redaction belongs
        # with the thing that stores it, so there is one place to check.
        sent = {"url": url, "method": "POST", "headers": dict(headers), "form": dict(form)}

        started = perf_counter()
        response: httpx.Response | None = None
        failure: Exception | None = None
        for attempt in range(1, self._ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
                    response = await client.post(url, data=form, headers=headers)
                failure = None
                break
            except httpx.HTTPError as exc:
                failure = exc
                log.warning(
                    "BT iPay %s attempt %d/%d failed: %s",
                    path,
                    attempt,
                    self._ATTEMPTS,
                    exc,
                )
        latency_ms = int((perf_counter() - started) * 1000)

        if failure is not None or response is None:
            await self._record(
                path=path,
                sent=sent,
                received={"network_error": str(failure)},
                http_status=None,
                error_code="network_error",
                error_message=str(failure),
                ok=False,
                latency_ms=latency_ms,
                provider_order_id=None,
            )
            raise PaymentProviderError(f"BT iPay could not be reached: {failure}")

        if response.status_code >= 500:
            await self._record(
                path=path,
                sent=sent,
                received={"body": response.text[:2000]},
                http_status=response.status_code,
                error_code=f"http_{response.status_code}",
                error_message=response.text[:500],
                ok=False,
                latency_ms=latency_ms,
                provider_order_id=None,
            )
            raise PaymentProviderError(f"BT iPay returned HTTP {response.status_code}.")

        try:
            body = response.json()
        except ValueError as exc:
            await self._record(
                path=path,
                sent=sent,
                received={"body": response.text[:2000]},
                http_status=response.status_code,
                error_code="not_json",
                error_message=response.text[:500],
                ok=False,
                latency_ms=latency_ms,
                provider_order_id=None,
            )
            raise PaymentProviderError("BT iPay returned something that is not JSON.") from exc

        error_code = str(body.get("errorCode") or "0")
        ok = error_code in ("0", "")
        if not ok:
            log.warning(
                "BT iPay %s errorCode=%s message=%s",
                path,
                error_code,
                body.get("errorMessage"),
            )
        await self._record(
            path=path,
            sent=sent,
            received=body,
            http_status=response.status_code,
            error_code=None if ok else error_code,
            error_message=None if ok else str(body.get("errorMessage") or "")[:500],
            ok=ok,
            latency_ms=latency_ms,
            provider_order_id=str(body["orderId"]) if body.get("orderId") else None,
        )
        return body

    async def _record(self, **entry: Any) -> None:
        """Write one journal line. Never lets the journal break the payment."""
        if self._journal is None:
            return
        try:
            await self._journal.record(provider=self.key, **entry)
        except Exception:
            log.exception("BT iPay journal write failed, continuing")

    # ------------------------------------------------------------- checkout

    async def create_checkout_session(
        self,
        *,
        order_ref: str,
        amount_minor: int,
        currency: str,
        return_url: str,
        metadata: dict[str, str] | None = None,
        buyer_email: str | None = None,
    ) -> CheckoutSession:
        """Register an order and return the hosted page to send the buyer to.

        One-phase by default: the money moves when the buyer authenticates.
        `metadata["preauth"]` switches to two-phase, where it is held and a
        later `deposit` captures it.
        """
        meta = metadata or {}
        two_phase = str(meta.get("preauth", "")).lower() in ("1", "true", "yes")
        path = "/payment/rest/registerPreAuth.do" if two_phase else "/payment/rest/register.do"

        numeric = _CURRENCY_NUMERIC.get((currency or "").upper())
        if not numeric:
            raise PaymentProviderError(f"BT iPay does not accept {currency}.")
        if amount_minor <= 0:
            raise PaymentProviderError("A payment must be for more than nothing.")

        params: dict[str, Any] = {
            # Unique per attempt. The gateway refuses a number it has seen, so
            # a buyer who returns to pay a second time — a new tab, a back
            # button, a retry after a failed authentication — would be refused
            # on a reference derived from the order alone.
            "orderNumber": f"{order_ref[:20].replace('|', '-')}-{uuid.uuid4().hex[:8]}",
            "amount": int(amount_minor),
            "currency": numeric,
            "returnUrl": return_url,
            "description": strip_diacritics(meta.get("description") or order_ref)[
                :_MAX_DESCRIPTION
            ],
            "orderBundle": self._order_bundle(meta, buyer_email),
        }
        if buyer_email:
            params["email"] = buyer_email
        if self.credentials.child_id:
            params["childId"] = self.credentials.child_id

        body = await self._post(path, params)
        order_id = body.get("orderId")
        form_url = body.get("formUrl")
        if not order_id or not form_url:
            raise PaymentProviderError(
                f"BT iPay refused the order: {body.get('errorMessage') or body}"
            )
        return CheckoutSession(
            session_id=str(order_id),
            url=str(form_url),
            raw={"btipay": body, "orderNumber": params["orderNumber"]},
        )

    def _order_bundle(self, meta: dict[str, str], buyer_email: str | None) -> dict[str, Any]:
        """The buyer's details, in the shape and alphabet the gateway accepts.

        Every part is omitted rather than filled in. A placeholder — "N/A", a
        dash, an empty string — is refused, and an address block containing
        neither a city nor a street is refused as a block, so it is left out
        whole. A club shop collected at the counter has no delivery address at
        all, and that is a supported shape here rather than a problem to paper
        over.
        """
        email = (buyer_email or meta.get("email") or "").strip()
        phone = normalise_phone(meta.get("phone"))
        city = strip_diacritics(meta.get("city"))[:_MAX_CITY]
        address = strip_diacritics(meta.get("address"))[:_MAX_POST_ADDRESS]

        buyer: dict[str, Any] = {}
        if email:
            buyer["email"] = email
        if phone:
            buyer["phone"] = phone
        if city or address:
            where: dict[str, Any] = {"country": _COUNTRY_RO}
            if city:
                where["city"] = city
            if address:
                where["postAddress"] = address
            buyer["deliveryInfo"] = where
            buyer["billingInfo"] = dict(where)

        bundle: dict[str, Any] = {
            "orderCreationDate": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        if buyer:
            bundle["customerDetails"] = buyer
        return bundle

    # --------------------------------------------------------------- status

    async def get_session_status(self, session_id: str) -> SessionStatus:
        body = await self._post(
            "/payment/rest/getOrderStatusExtended.do", {"orderId": session_id}
        )
        if str(body.get("errorCode") or "0") != "0":
            return SessionStatus(
                status="failed",
                currency=str(body.get("currency") or "RON"),
                raw=body,
            )

        try:
            code = int(body.get("orderStatus"))
        except (TypeError, ValueError):
            code = -1
        state = _ORDER_STATUS.get(code, "pending")

        amounts = body.get("paymentAmountInfo") or {}
        paid = int(amounts.get("depositedAmount") or 0)
        if state == "approved":
            paid = int(amounts.get("approvedAmount") or paid)

        return SessionStatus(
            status=state,
            paid_amount_minor=paid,
            currency=str(body.get("currency") or "RON"),
            raw=body,
        )

    # -------------------------------------------------------------- capture

    async def deposit(self, session_id: str, amount_minor: int) -> dict[str, Any]:
        """Capture a held authorisation. Two-phase only."""
        return await self._expect_ok(
            "/payment/rest/deposit.do",
            {"orderId": session_id, "amount": int(amount_minor)},
            "capture",
        )

    async def reverse(self, session_id: str) -> dict[str, Any]:
        """Release a held authorisation, while it is still held."""
        return await self._expect_ok(
            "/payment/rest/reverse.do", {"orderId": session_id}, "release"
        )

    async def refund(self, session_id: str, amount_minor: int) -> dict[str, Any]:
        """Return money on a captured order, in full or in part."""
        return await self._expect_ok(
            "/payment/rest/refund.do",
            {"orderId": session_id, "amount": int(amount_minor)},
            "refund",
        )

    async def _expect_ok(self, path: str, params: dict[str, Any], what: str) -> dict[str, Any]:
        body = await self._post(path, params)
        code = str(body.get("errorCode") or "0")
        if code != "0":
            raise PaymentProviderError(
                f"BT iPay could not {what} this order ({code}): "
                f"{body.get('errorMessage') or 'no reason given'}"
            )
        return body

    # ----------------------------------------------------------- diagnostic

    async def test_connection(self) -> dict[str, Any]:
        """Ask about an order that cannot exist, and read the refusal.

        `6 — no such order` is the answer to a well-formed question from
        somebody who is allowed to ask, which is exactly what needs proving.
        `5 — access denied` is the credentials being wrong. Nothing is
        registered and no money moves either way.
        """
        body = await self._post(
            "/payment/rest/getOrderStatusExtended.do", {"orderId": str(uuid.uuid4())}
        )
        code = str(body.get("errorCode") or "0")
        if code == "6":
            return {"ok": True, "sandbox": self.credentials.sandbox, "raw": body}
        if code == "5":
            return {
                "ok": False,
                "error": "BT iPay refused the user name or password.",
                "sandbox": self.credentials.sandbox,
                "raw": body,
            }
        return {
            "ok": code == "0",
            "error": body.get("errorMessage"),
            "sandbox": self.credentials.sandbox,
            "raw": body,
        }
