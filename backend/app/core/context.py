"""Request-scoped context.

Tenant identity is resolved once, by middleware, and then flows implicitly to
the database session, the logger and every service. Nothing downstream accepts
a tenant id as an argument, because an argument can be passed wrongly.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.errors import TenantContextMissing

if TYPE_CHECKING:  # pragma: no cover
    from app.authz.permissions import EffectivePermissions
    from app.authz.scope import Scope
    from app.billing.service import Entitlements


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller."""

    user_id: UUID
    subject_id: str
    email: str
    is_platform_user: bool = False
    auth_time: datetime | None = None
    amr: frozenset[str] = field(default_factory=frozenset)
    impersonated_by: UUID | None = None

    @property
    def has_second_factor(self) -> bool:
        return bool(self.amr & {"otp", "mfa", "hwk", "swk", "webauthn"})


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Everything a service needs to know about who is asking, and on whose behalf."""

    request_id: str
    tenant_id: UUID | None = None
    principal: Principal | None = None
    permissions: EffectivePermissions | None = None
    entitlements: Entitlements | None = None
    scope: Scope | None = None
    person_id: UUID | None = None

    @property
    def tenant(self) -> UUID:
        if self.tenant_id is None:
            raise TenantContextMissing()
        return self.tenant_id

    @property
    def actor(self) -> Principal:
        if self.principal is None:
            raise TenantContextMissing("No authenticated principal on this request.")
        return self.principal

    @property
    def actor_id(self) -> UUID | None:
        return self.principal.user_id if self.principal else None


_tenant_id: ContextVar[UUID | None] = ContextVar("tenant_id", default=None)
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_platform_scope: ContextVar[bool] = ContextVar("platform_scope", default=False)


def current_tenant_id() -> UUID:
    value = _tenant_id.get()
    if value is None:
        raise TenantContextMissing()
    return value


def current_tenant_id_optional() -> UUID | None:
    return _tenant_id.get()


def set_tenant_id(tenant_id: UUID | None) -> Token[UUID | None]:
    return _tenant_id.set(tenant_id)


def reset_tenant_id(token: Token[UUID | None]) -> None:
    _tenant_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


def set_request_id(request_id: str) -> Token[str | None]:
    return _request_id.set(request_id)


def in_platform_scope() -> bool:
    return _platform_scope.get()


def set_platform_scope(active: bool) -> Token[bool]:
    return _platform_scope.set(active)


def reset_platform_scope(token: Token[bool]) -> None:
    _platform_scope.reset(token)
