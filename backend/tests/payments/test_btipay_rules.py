"""The gateway's rules about what it will accept, pinned.

Every rule here is one BT iPay enforces by refusing a registration, usually
with an error that names something other than the real cause. They are cheap to
assert and expensive to rediscover: the failure mode is a supporter who cannot
pay, and an error message pointing at the merchant configuration rather than at
the address field.

No network. These are the pure functions that shape a request, plus the reading
of a reply — which is the part that decides whether money moved.
"""

from __future__ import annotations

import pytest

from app.payments.base import PaymentProviderError
from app.payments.btipay import (
    LIVE_ORDER_STATUSES,
    PAID_ORDER_STATUS,
    BtIpayProvider,
    normalise_phone,
    strip_diacritics,
)
from app.payments.journal import REDACTED, redact

pytestmark = pytest.mark.commerce


def provider(**kwargs) -> BtIpayProvider:
    return BtIpayProvider(user_name="u", password="p", **kwargs)


class TestWhatTheGatewayWillRead:
    """Diacritics, newlines and length — the three refusals."""

    def test_romanian_place_names_lose_their_marks_and_keep_their_letters(self) -> None:
        """`2003 — Non-3DS transaction forbidden for merchant` is what a
        diacritic gets you, which reads like a contract problem and is not."""
        assert strip_diacritics("Constanța") == "Constanta"
        assert strip_diacritics("Vârful cu Dor") == "Varful cu Dor"
        assert strip_diacritics("Reșița") == "Resita"
        # The cedilla spellings, which is what half of Romanian text uses.
        assert strip_diacritics("Ştefăneşti") == "Stefanesti"

    def test_a_newline_becomes_a_space(self) -> None:
        """An address pasted from a form arrives with the line breaks the
        person typed. The gateway forbids the character outright."""
        assert strip_diacritics("Str. Lungă 12\nBl. A, Ap. 3") == "Str. Lunga 12 Bl. A, Ap. 3"
        assert strip_diacritics("  double   spaced  ") == "double spaced"

    def test_nothing_is_still_nothing(self) -> None:
        assert strip_diacritics(None) == ""
        assert strip_diacritics("") == ""

    def test_the_address_block_is_cut_to_the_gateway_limits(self) -> None:
        """Fifty for the street, forty for the town. A live registration was
        refused at fifty-four characters and accepted at forty-eight."""
        bundle = provider()._order_bundle(
            {"city": "C" * 60, "address": "A" * 80, "phone": "0740123456"},
            None,
        )
        where = bundle["customerDetails"]["deliveryInfo"]
        assert len(where["city"]) == 40
        assert len(where["postAddress"]) == 50

    def test_the_description_is_cut_too(self) -> None:
        assert len(strip_diacritics("x" * 200)[:125]) == 125


class TestThePhoneNumber:
    def test_a_romanian_number_as_anybody_writes_it(self) -> None:
        assert normalise_phone("0740 123 456") == "40740123456"
        assert normalise_phone("+40 740 123 456") == "40740123456"
        assert normalise_phone("0040740123456") == "40740123456"

    def test_one_already_international_is_left_alone(self) -> None:
        assert normalise_phone("40740123456") == "40740123456"

    def test_nothing_usable_is_nothing(self) -> None:
        assert normalise_phone(None) == ""
        assert normalise_phone("   ") == ""
        assert normalise_phone("n/a") == ""


class TestTheAddressBlock:
    """A club shop is collected at the counter. There is no delivery address,
    and inventing one is worse than having none."""

    def test_an_absent_address_is_omitted_rather_than_filled_in(self) -> None:
        """ "N/A" in postAddress is refused. So is an empty string."""
        bundle = provider()._order_bundle({"phone": "0740123456"}, "fan@example.com")
        details = bundle["customerDetails"]
        assert "deliveryInfo" not in details
        assert "billingInfo" not in details
        assert details["email"] == "fan@example.com"
        assert details["phone"] == "40740123456"

    def test_a_buyer_who_gave_nothing_carries_no_customer_block_at_all(self) -> None:
        bundle = provider()._order_bundle({}, None)
        assert "customerDetails" not in bundle
        assert "orderCreationDate" in bundle

    def test_billing_matches_delivery_and_names_the_country(self) -> None:
        bundle = provider()._order_bundle({"city": "Resita", "address": "Str. Mare 1"}, None)
        details = bundle["customerDetails"]
        assert details["deliveryInfo"] == details["billingInfo"]
        assert details["deliveryInfo"]["country"] == "642"


class TestReadingTheReply:
    """Two of the gateway's states mean "somebody is paying right now", and
    both arrive as the same word as "nobody has tried". The number is what
    reconciliation must read; the word is only fit for showing a buyer."""

    def test_the_states_that_must_never_be_cancelled(self) -> None:
        # 1 = money held. 5 = the buyer is on their bank's screen.
        assert set(LIVE_ORDER_STATUSES) == {1, 5}
        # 0 = registered and abandoned, 6 = refused. Both safe to let go.
        assert 0 not in LIVE_ORDER_STATUSES
        assert 6 not in LIVE_ORDER_STATUSES

    def test_only_one_state_means_the_money_moved(self) -> None:
        assert PAID_ORDER_STATUS == 2


class TestCredentials:
    def test_half_a_credential_is_refused_at_construction(self) -> None:
        """Rather than at the moment a supporter is trying to pay."""
        with pytest.raises(PaymentProviderError):
            BtIpayProvider(user_name="u", password="")
        with pytest.raises(PaymentProviderError):
            BtIpayProvider(user_name="", password="p")

    def test_sandbox_and_production_are_different_hosts(self) -> None:
        assert "sandbox" in provider(sandbox=True).credentials.base_url
        assert "sandbox" not in provider(sandbox=False).credentials.base_url

    def test_the_password_never_appears_in_the_journal(self) -> None:
        """The record is evidence, so it keeps everything — except the thing
        that would let a reader of the record take payments themselves."""
        sent = {
            "headers": {"Authorization": "Basic dTpw", "Content-Type": "text/plain"},
            "form": {"amount": "1000", "orderNumber": "so_1-abcd1234"},
        }
        cleaned = redact(sent)
        assert cleaned["headers"]["Authorization"] == REDACTED
        # Everything else survives verbatim — that is the point of keeping it.
        assert cleaned["headers"]["Content-Type"] == "text/plain"
        assert cleaned["form"] == sent["form"]

    def test_a_bearer_token_anywhere_in_the_body_goes_too(self) -> None:
        assert redact({"note": "Bearer abc.def"})["note"] == f"Bearer {REDACTED}"
        assert redact([{"password": "hunter2"}]) == [{"password": REDACTED}]
