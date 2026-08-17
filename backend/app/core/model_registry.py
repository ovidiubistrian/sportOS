"""Single import point for every mapped model.

Alembic autogenerate, the isolation sweep and the RLS migration helper all need
the full metadata. Importing modules individually in several places is how a
table quietly ends up missing from a migration — so there is exactly one list,
here, and everything imports it.

Adding a module means adding one line.
"""

from __future__ import annotations

from app.ai import models as ai_models
from app.analytics import models as analytics_models
from app.audit import models as audit_models
from app.authz import models as authz_models
from app.billing import models as billing_models
from app.cms import models as cms_models
from app.commerce import models as commerce_models
from app.competitions import models as competition_models
from app.events import models as events_models
from app.fans import models as fans_models
from app.fans import supporter_models as supporter_models
from app.identity import models as identity_models
from app.integrations import models as integrations_models
from app.marketing import models as marketing_models
from app.media import models as media_models
from app.ordering import models as ordering_models
from app.payments import models as payments_models
from app.players import models as players_models
from app.teams import models as teams_models
from app.tenants import branding_models as tenants_branding_models
from app.tenants import models as tenants_models
from app.ticketing import access_models as ticketing_access_models
from app.ticketing import event_models as ticketing_event_models
from app.ticketing import ticket_models as ticketing_ticket_models
from app.ticketing import venue_models as ticketing_venue_models

__all__ = [
    "ai_models",
    "analytics_models",
    "audit_models",
    "authz_models",
    "billing_models",
    "cms_models",
    "commerce_models",
    "competition_models",
    "events_models",
    "fans_models",
    "identity_models",
    "integrations_models",
    "marketing_models",
    "media_models",
    "ordering_models",
    "payments_models",
    "players_models",
    "supporter_models",
    "teams_models",
    "tenants_branding_models",
    "tenants_models",
    "ticketing_access_models",
    "ticketing_event_models",
    "ticketing_ticket_models",
    "ticketing_venue_models",
]
