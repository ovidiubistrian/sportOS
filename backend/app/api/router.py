"""API v1 composition.

Each module owns its router; this file only mounts them. Adding a module means
one import and one `include_router` — nothing else in the application changes.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.ai.router import router as ai_router
from app.analytics.public_router import router as analytics_public_router
from app.analytics.router import router as analytics_router
from app.authz.staff_router import router as staff_router
from app.billing.public_router import router as plans_router
from app.cms.router import router as cms_router
from app.commerce.public_router import router as shop_public_router
from app.commerce.router import router as shop_router
from app.competitions.router import router as competitions_router
from app.fans.router import router as fans_router
from app.fans.supporter_router import router as supporter_router
from app.identity.registration_router import router as registration_router
from app.identity.router import router as identity_router
from app.integrations.api_football.club_router import router as club_feed_router
from app.integrations.api_football.router import router as feed_router
from app.marketing.public_router import router as marketing_public_router
from app.marketing.router import router as marketing_router
from app.media.router import router as media_router
from app.platform.ai_router import router as ai_platform_router
from app.platform.router import router as platform_router
from app.players.router import router as players_router
from app.sports.router import router as sports_router
from app.teams.router import router as teams_router
from app.tenants.branding_router import router as branding_router
from app.tenants.public_router import router as public_router

api_v1 = APIRouter()

api_v1.include_router(identity_router)
api_v1.include_router(registration_router)
api_v1.include_router(staff_router)
api_v1.include_router(analytics_router)
api_v1.include_router(sports_router)
api_v1.include_router(teams_router)
api_v1.include_router(players_router)
api_v1.include_router(branding_router)
api_v1.include_router(cms_router)
api_v1.include_router(competitions_router)
api_v1.include_router(shop_router)
api_v1.include_router(plans_router)
api_v1.include_router(ai_router)
api_v1.include_router(marketing_router)
api_v1.include_router(media_router)
api_v1.include_router(ai_platform_router)
api_v1.include_router(platform_router)
api_v1.include_router(feed_router)
api_v1.include_router(club_feed_router)

# Unauthenticated, host-scoped, CDN-cacheable. Mounted last so its prefix
# cannot shadow an authenticated route.
api_v1.include_router(public_router)
api_v1.include_router(shop_public_router)
api_v1.include_router(fans_router)
api_v1.include_router(analytics_public_router)
api_v1.include_router(marketing_public_router)
api_v1.include_router(supporter_router)
