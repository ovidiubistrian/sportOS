"""Every model is deliberately tenant-scoped or deliberately global.

This is the test that stops the slow leak: someone adds a table in a hurry,
forgets `tenant_id`, and nothing complains until a customer sees another
customer's data. Here, the new model fails CI on the day it is written.
"""

from __future__ import annotations

import pytest

from app.core import model_registry  # noqa: F401  registers all metadata
from app.core.models import Base, is_tenant_scoped

# Tables that are legitimately not tenant-scoped. Adding a name here is a
# deliberate, reviewable act — which is the entire point of the allow-list.
GLOBAL_MODELS = {
    "tenant",  # it *is* the tenant; has its own policy on `id`
    "user_account",  # one login may be a person in several tenants
    "permission",  # static reference data
    "role",  # system templates have no tenant
    "role_permission",
    "role_assignment",  # read during bootstrap, before a tenant is known
    # Infrastructure: the relay claims across all tenants before any tenant
    # context exists, and both are reachable only by platform-role processes.
    "outbox_event",
    "processed_event",
    # Plan catalogue: global reference data, identical for every tenant.
    "feature",
    "plan",
    "plan_version",
    "plan_feature",
    "plan_price",
    # Football's own reference data, shared by every tenant: the country
    # pyramid, the competitions in it, the club directory and the fixtures.
    # A match between two clubs is one event — if each tenant kept a copy, the
    # same fixture would exist twice with two scorelines and no league table
    # could ever be computed. See app/competitions/models.py.
    "country",
    "competition",
    "competition_season",
    "competition_entry",
    "directory_club",
    "match",
    "match_event",  # two clubs play one game; one set of goals
    "match_lineup",  # and one team sheet per side, not one per tenant
    "match_lineup_player",
    "club_season_record",  # a club's finishing position is public record
    # Provider mappings for the reference data above. A fixture's API-Football
    # id is a property of the fixture, which no tenant owns; keeping a copy per
    # tenant would mean two tenants in one league syncing the same match twice.
    "provider_link",
    "provider_sync_run",
    # Nullable tenant_id (platform actions have no tenant), so not TenantScoped —
    # but each still carries an RLS policy. See POLICY_ON_GLOBAL_TABLES.
    "audit_log",
    "entitlement",
    "tenant_subscription",
}

pytestmark = pytest.mark.isolation


def _mapped_models() -> list[type]:
    return [mapper.class_ for mapper in Base.registry.mappers]


def test_every_model_declares_its_tenancy() -> None:
    undeclared = [
        model.__name__
        for model in _mapped_models()
        if not is_tenant_scoped(model) and model.__tablename__ not in GLOBAL_MODELS
    ]
    assert not undeclared, (
        f"These models are neither TenantScoped nor on the GLOBAL_MODELS "
        f"allow-list: {sorted(undeclared)}. If the table holds tenant data, "
        f"inherit TenantScoped. If it genuinely does not, add it to the "
        f"allow-list with a comment saying why."
    )


def test_tenant_scoped_models_have_a_tenant_id_column() -> None:
    for model in _mapped_models():
        if not is_tenant_scoped(model):
            continue
        columns = {c.name for c in model.__table__.columns}
        assert "tenant_id" in columns, f"{model.__name__} is TenantScoped without tenant_id"
        assert not model.__table__.c.tenant_id.nullable, (
            f"{model.__name__}.tenant_id must be NOT NULL — a nullable tenant "
            f"column creates rows that belong to nobody and are visible to no one."
        )


def test_allow_list_has_no_stale_entries() -> None:
    known = {model.__tablename__ for model in _mapped_models()}
    stale = GLOBAL_MODELS - known
    assert not stale, f"GLOBAL_MODELS lists tables that no longer exist: {sorted(stale)}"
