"""Domain error hierarchy and the single mapping to HTTP responses.

Rules:
  * Domain code raises domain errors. It never constructs an HTTP response.
  * Every error carries a stable `code` that is part of the public API contract
    and safe for the frontend to branch on.
  * Nothing internal (SQL, stack traces, provider payloads) reaches a client.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base for every expected, mapped failure."""

    code: str = "INTERNAL_ERROR"
    status: int = 500
    default_message: str = "Something went wrong."

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.default_message
        self.details: dict[str, Any] = details
        super().__init__(self.message)


# --- Generic ---------------------------------------------------------------


class ValidationFailed(DomainError):
    code, status = "VALIDATION_ERROR", 422
    default_message = "The submitted data is not valid."


class NotFound(DomainError):
    """Also raised when an object exists but is outside the caller's scope.

    Returning 404 rather than 403 for out-of-scope objects is deliberate: a 403
    confirms the object exists, which is itself an information leak.
    """

    code, status = "NOT_FOUND", 404
    default_message = "The requested resource does not exist."


class Conflict(DomainError):
    code, status = "CONFLICT", 409
    default_message = "The request conflicts with the current state."


class StaleResource(Conflict):
    code = "STALE_RESOURCE"
    default_message = "The resource changed since you loaded it."


# --- Authentication and authorization --------------------------------------


class Unauthenticated(DomainError):
    code, status = "UNAUTHENTICATED", 401
    default_message = "Authentication is required."


class StepUpRequired(DomainError):
    code, status = "STEP_UP_REQUIRED", 401
    default_message = "This action requires recent strong authentication."


class PermissionDenied(DomainError):
    code, status = "PERMISSION_DENIED", 403
    default_message = "You do not have permission to perform this action."


class TenantMismatch(DomainError):
    code, status = "TENANT_MISMATCH", 400
    default_message = "The request refers to a different tenant."


class TenantContextMissing(DomainError):
    code, status = "TENANT_CONTEXT_MISSING", 400
    default_message = "The tenant could not be determined for this request."


class TenantSuspended(DomainError):
    code, status = "TENANT_SUSPENDED", 403
    default_message = "This account is suspended."


# --- Entitlements ----------------------------------------------------------


class FeatureNotEnabled(DomainError):
    code, status = "FEATURE_NOT_ENABLED", 402
    default_message = "This feature is not included in your plan."


class LimitExceeded(DomainError):
    code, status = "LIMIT_EXCEEDED", 409
    default_message = "You have reached the limit for your plan."


# --- Ticketing / commerce (declared now; used from Phase 2) ----------------


class SeatUnavailable(DomainError):
    code, status = "SEAT_UNAVAILABLE", 423
    default_message = "That seat is no longer available."


class TicketAlreadyUsed(DomainError):
    code, status = "TICKET_ALREADY_USED", 409
    default_message = "This ticket has already been scanned."


class MembershipExpired(DomainError):
    code, status = "MEMBERSHIP_EXPIRED", 409
    default_message = "This membership has expired."


class PaymentRequired(DomainError):
    code, status = "PAYMENT_REQUIRED", 402
    default_message = "Payment is required to continue."


class IdempotencyKeyReuse(Conflict):
    code = "IDEMPOTENCY_KEY_REUSED"
    default_message = "This idempotency key was used with a different request."


class RateLimited(DomainError):
    code, status = "RATE_LIMITED", 429
    default_message = "Too many requests."
