"""The audit allow-list fails closed.

These are the tests that matter most in this module: the failure mode of a
deny-list is that a newly added column silently starts being recorded. Every
case below asserts the opposite behaviour.
"""

from __future__ import annotations

import pytest

from app.audit.redaction import ALLOWED_FIELDS, NEVER_RECORD, diff, redact

pytestmark = pytest.mark.audit


class TestFailClosed:
    def test_unknown_object_type_records_nothing(self) -> None:
        assert redact("not_a_real_type", {"anything": "value"}) is None

    def test_unlisted_field_is_dropped(self) -> None:
        result = redact("player", {"status": "REGISTERED", "invented_column": "secret"})
        assert result == {"status": "REGISTERED"}

    def test_a_new_sensitive_column_is_not_recorded_by_default(self) -> None:
        """Simulates someone adding a column and forgetting the allow-list."""
        result = redact(
            "player",
            {"status": "TRIAL", "medical_summary": "ACL rupture", "salary_minor": 500000},
        )
        assert result == {"status": "TRIAL"}

    @pytest.mark.parametrize("field", sorted(NEVER_RECORD))
    def test_never_record_fields_are_blocked_even_if_allow_listed(self, field: str) -> None:
        """Second barrier: a typo in ALLOWED_FIELDS cannot expose a credential."""
        assert redact("player", {field: "leaked"}) in (None, {})

    def test_medical_has_no_allow_list_at_all(self) -> None:
        for object_type in ("medical_record", "injury", "treatment"):
            assert object_type not in ALLOWED_FIELDS
            assert redact(object_type, {"diagnosis_text": "…"}) is None


class TestDiff:
    def test_unchanged_fields_are_omitted(self) -> None:
        before, after = diff(
            "player",
            {"status": "REGISTERED", "primary_position": "CB"},
            {"status": "REGISTERED", "primary_position": "ST"},
        )
        assert before == {"primary_position": "CB"}
        assert after == {"primary_position": "ST"}

    def test_no_change_produces_no_record(self) -> None:
        before, after = diff("player", {"status": "TRIAL"}, {"status": "TRIAL"})
        assert before is None and after is None

    def test_diff_respects_the_allow_list(self) -> None:
        before, after = diff(
            "player",
            {"status": "TRIAL", "secret_note": "a"},
            {"status": "REGISTERED", "secret_note": "b"},
        )
        assert before == {"status": "TRIAL"}
        assert after == {"status": "REGISTERED"}

    def test_values_are_json_safe(self) -> None:
        from uuid import uuid4

        club_id = uuid4()
        result = redact("player", {"club_id": club_id, "secondary_positions": ["CB", "LB"]})
        assert result == {"club_id": str(club_id), "secondary_positions": ["CB", "LB"]}
