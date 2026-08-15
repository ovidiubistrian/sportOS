"""Keycloak administration.

The only place the application creates or deletes a login. It holds a service
account with exactly one realm-management role — `manage-users` — because a
sign-up form should not be able to change the realm's own configuration.

Passwords pass through this module and stop here: they are sent to Keycloak and
never stored, never logged, and never returned. Nothing in this file writes a
credential to a log line, and the exception types are chosen so a stack trace
cannot carry one either.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

from app.core.config import settings
from app.core.errors import Conflict, DomainError

log = structlog.get_logger(__name__)


class IdentityProviderUnavailable(DomainError):
    code, status = "IDENTITY_UNAVAILABLE", 503
    default_message = "We could not create your account just now. Please try again."


class EmailAlreadyRegistered(Conflict):
    code = "EMAIL_ALREADY_REGISTERED"
    default_message = "There is already an account with that email address."


@dataclass(frozen=True, slots=True)
class CreatedUser:
    subject_id: str
    email: str


def _admin_base() -> str:
    # The issuer is `<base>/realms/<realm>`; the admin API lives beside it.
    issuer = settings.oidc_issuer.rstrip("/")
    base, _, realm = issuer.rpartition("/realms/")
    return f"{base}/admin/realms/{realm}"


class KeycloakAdmin:
    """A thin client over the bits of the Admin API we actually use.

    Two service accounts, deliberately. `footbola-registration` may create
    users and nothing else; `footbola-domains` may edit the supporter client's
    redirect list and nothing else. Splitting them means a flaw in the public
    sign-up path cannot reconfigure the realm, and a flaw in domain handling
    cannot mint logins — which one account holding both roles would allow.
    """

    def __init__(self) -> None:
        self._token: str | None = None
        self._domains_token: str | None = None

    async def _access_token(self, client: httpx.AsyncClient, *, refresh: bool = False) -> str:
        """The service-account token, cached until it stops working.

        Keycloak's client-credentials tokens are short-lived — a minute by
        default. Caching one forever means sign-up works after a deploy and
        starts returning 503 an hour later, which is exactly the failure that
        looks like "the identity provider is down" and is not.

        Rather than track expiry (clock skew, refresh windows, a background
        task), the token is dropped when a call comes back 401 and fetched
        again. One wasted request per expiry, and no clock to get wrong.
        """
        if self._token and not refresh:
            return self._token
        issuer = settings.oidc_issuer.rstrip("/")
        response = await client.post(
            f"{issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.registration_client_id,
                "client_secret": settings.registration_client_secret.get_secret_value(),
            },
        )
        if response.status_code != 200:
            log.error("keycloak_service_token_failed", status=response.status_code)
            raise IdentityProviderUnavailable()
        self._token = str(response.json()["access_token"])
        return self._token

    async def create_user(
        self, *, email: str, password: str, first_name: str, last_name: str
    ) -> CreatedUser:
        """Create a login and send the verification email.

        The account is created **unverified and with the email-verification
        action pending**. That is what stops someone claiming a club's identity
        with an address they do not control — the tenant exists but stays
        `PENDING` until Keycloak confirms the address.
        """
        async with httpx.AsyncClient(timeout=settings.identity_timeout_seconds) as client:
            token = await self._access_token(client)
            headers = {"Authorization": f"Bearer {token}"}

            payload = {
                "username": email,
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "enabled": True,
                "emailVerified": False,
                "requiredActions": ["VERIFY_EMAIL"],
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            }
            response = await client.post(
                f"{_admin_base()}/users", headers=headers, json=payload
            )

            if response.status_code == 401:
                headers = {
                    "Authorization": f"Bearer {await self._access_token(client, refresh=True)}"
                }
                response = await client.post(
                    f"{_admin_base()}/users", headers=headers, json=payload
                )

            if response.status_code == 409:
                # Deliberately the same answer whether the address exists or
                # not is *not* possible here — the caller has to know, or it
                # cannot proceed. The trade is accepted: sign-up leaks that an
                # address is registered, which every sign-up form does.
                raise EmailAlreadyRegistered()

            if response.status_code not in (201, 204):
                log.error(
                    "keycloak_create_user_failed",
                    status=response.status_code,
                    # Never the body: it echoes the submitted representation,
                    # which contains the password.
                )
                raise IdentityProviderUnavailable()

            location = response.headers.get("Location", "")
            subject_id = location.rstrip("/").rsplit("/", 1)[-1]
            if not subject_id:
                raise IdentityProviderUnavailable()

            await self.send_verification_email(subject_id)
            log.info("keycloak_user_created", subject_id=subject_id)
            return CreatedUser(subject_id=subject_id, email=email)

    async def _domains_access_token(
        self, client: httpx.AsyncClient, *, refresh: bool = False
    ) -> str:
        """The token for the account that may edit clients, and only clients."""
        if self._domains_token and not refresh:
            return self._domains_token

        issuer = settings.oidc_issuer.rstrip("/")
        response = await client.post(
            f"{issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.domains_client_id,
                "client_secret": settings.domains_client_secret.get_secret_value(),
            },
        )
        if response.status_code != 200:
            log.error("keycloak_domains_token_failed", status=response.status_code)
            raise IdentityProviderUnavailable()
        self._domains_token = str(response.json()["access_token"])
        return self._domains_token

    async def allow_redirect(self, hostname: str) -> bool:
        """Let supporters sign in on one more club domain.

        Every club's supporters return to *their own* address after Keycloak,
        so each domain has to be a registered redirect URI on the supporter
        client. Without this a new club's website has a sign-in button that
        ends on Keycloak's "Invalid parameter: redirect_uri" page.

        Idempotent, and additive only: a domain that is already listed is left
        alone, and nothing is ever removed — a club that drops a domain still
        has supporters holding links to it.
        """
        client_id = settings.supporter_client_id
        wanted = [f"http://{hostname}/*", f"https://{hostname}/*"]

        async with httpx.AsyncClient(timeout=settings.identity_timeout_seconds) as client:
            token = await self._domains_access_token(client)
            headers = {"Authorization": f"Bearer {token}"}

            found = await client.get(
                f"{_admin_base()}/clients",
                headers=headers,
                params={"clientId": client_id},
            )
            if found.status_code == 401:
                fresh = await self._domains_access_token(client, refresh=True)
                headers = {"Authorization": f"Bearer {fresh}"}
                found = await client.get(
                    f"{_admin_base()}/clients",
                    headers=headers,
                    params={"clientId": client_id},
                )

            if found.status_code != 200 or not found.json():
                log.warning("keycloak_supporter_client_missing", client_id=client_id)
                return False

            record = found.json()[0]
            redirects = list(record.get("redirectUris") or [])
            missing = [uri for uri in wanted if uri not in redirects]
            if not missing:
                return True

            redirects.extend(missing)
            attributes = dict(record.get("attributes") or {})
            logout = [
                uri
                for uri in (attributes.get("post.logout.redirect.uris") or "").split("##")
                if uri
            ]
            logout.extend(uri for uri in wanted if uri not in logout)
            attributes["post.logout.redirect.uris"] = "##".join(logout)

            updated = await client.put(
                f"{_admin_base()}/clients/{record['id']}",
                headers=headers,
                json={"redirectUris": redirects, "attributes": attributes},
            )
            if updated.status_code not in (200, 204):
                log.warning(
                    "keycloak_redirect_not_added",
                    hostname=hostname,
                    status=updated.status_code,
                )
                return False

            log.info("keycloak_redirect_added", hostname=hostname)
            return True

    async def find_by_email(self, email: str) -> str | None:
        """The subject id behind an address, if the realm knows it.

        Needed because a club inviting somebody is often inviting somebody the
        platform already knows — a coach at a second club, a supporter who is
        now doing the news. Creating a second login for them would split one
        person into two accounts with no way back.
        """
        async with httpx.AsyncClient(timeout=settings.identity_timeout_seconds) as client:
            token = await self._access_token(client)
            response = await client.get(
                f"{_admin_base()}/users",
                headers={"Authorization": f"Bearer {token}"},
                params={"email": email, "exact": "true"},
            )
            if response.status_code == 401:
                response = await client.get(
                    f"{_admin_base()}/users",
                    headers={
                        "Authorization": (
                            f"Bearer {await self._access_token(client, refresh=True)}"
                        )
                    },
                    params={"email": email, "exact": "true"},
                )
            if response.status_code != 200:
                log.error("keycloak_find_user_failed", status=response.status_code)
                raise IdentityProviderUnavailable()

            found = response.json()
            return str(found[0]["id"]) if found else None

    async def invite_user(
        self,
        *,
        email: str,
        first_name: str,
        last_name: str,
        temporary_password: str | None = None,
    ) -> CreatedUser:
        """Create a login, either by invitation link or with a starting password.

        The link is the better of the two and stays the default: nobody else
        ever knows the person's password, and there is nothing to read out over
        the phone. But a club whose coach has no working email — or who is
        standing in the room — needs to hand over something that works today,
        so a starting password is allowed and marked **temporary**: Keycloak
        forces a change at first sign-in, and what the administrator typed
        stops being a credential the moment it is used once.

        An address the realm already knows is returned rather than refused —
        being invited to a second club is normal, and it is the same person.
        """
        existing = await self.find_by_email(email)
        if existing:
            log.info("keycloak_user_reused", subject_id=existing)
            return CreatedUser(subject_id=existing, email=email)

        async with httpx.AsyncClient(timeout=settings.identity_timeout_seconds) as client:
            token = await self._access_token(client)
            headers = {"Authorization": f"Bearer {token}"}

            payload: dict[str, object] = {
                "username": email,
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "enabled": True,
                # Marked verified only on the password path, and only because
                # the club administrator is vouching for this person in the
                # room. The realm requires a verified address before anybody
                # may sign in, so leaving it false here would create an account
                # that can never be finished — which is the whole case this
                # path exists for. On the link path the address proves itself.
                "emailVerified": bool(temporary_password),
                # Verifying the address is required of somebody who arrives by
                # link — the link went to that address, so proving it costs
                # them nothing. It is *not* required of somebody handed a
                # starting password, because the whole reason for that path is
                # an address that cannot receive: demanding verification would
                # make the account impossible to finish setting up.
                "requiredActions": (
                    ["UPDATE_PASSWORD"]
                    if temporary_password
                    else ["UPDATE_PASSWORD", "VERIFY_EMAIL"]
                ),
            }
            if temporary_password:
                # `temporary: true` is the whole point — Keycloak refuses to let
                # them past the login screen without setting their own.
                payload["credentials"] = [
                    {
                        "type": "password",
                        "value": temporary_password,
                        "temporary": True,
                    }
                ]
            response = await client.post(
                f"{_admin_base()}/users", headers=headers, json=payload
            )
            if response.status_code == 401:
                headers = {
                    "Authorization": f"Bearer {await self._access_token(client, refresh=True)}"
                }
                response = await client.post(
                    f"{_admin_base()}/users", headers=headers, json=payload
                )

            if response.status_code == 409:
                # Lost a race with another invitation of the same address.
                found = await self.find_by_email(email)
                if found:
                    return CreatedUser(subject_id=found, email=email)
                raise EmailAlreadyRegistered()

            if response.status_code not in (201, 204):
                log.error("keycloak_invite_failed", status=response.status_code)
                raise IdentityProviderUnavailable()

            subject_id = response.headers.get("Location", "").rstrip("/").rsplit("/", 1)[-1]
            if not subject_id:
                raise IdentityProviderUnavailable()

            if not temporary_password:
                await self.send_invitation_email(subject_id)
            log.info(
                "keycloak_user_invited",
                subject_id=subject_id,
                by_link=not temporary_password,
            )
            return CreatedUser(subject_id=subject_id, email=email)

    async def send_invitation_email(self, subject_id: str) -> None:
        """Ask Keycloak to email a set-your-password link.

        Same swallow-and-log posture as the verification mail: the grant is
        already written, and a mail server hiccup must not undo somebody's job
        title. The club can send it again from the staff screen.
        """
        try:
            async with httpx.AsyncClient(timeout=settings.identity_timeout_seconds) as client:
                token = await self._access_token(client)
                response = await client.put(
                    f"{_admin_base()}/users/{subject_id}/execute-actions-email",
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "client_id": settings.registration_redirect_client,
                        # Long enough to survive a weekend and a spam folder.
                        "lifespan": 60 * 60 * 24 * 3,
                    },
                    json=["UPDATE_PASSWORD", "VERIFY_EMAIL"],
                )
                if response.status_code not in (200, 204):
                    log.warning("keycloak_invitation_email_failed", status=response.status_code)
        except httpx.HTTPError as exc:
            log.warning("keycloak_invitation_email_error", error=str(exc))

    async def send_verification_email(self, subject_id: str) -> None:
        """Ask Keycloak to send (or resend) the verification message.

        A failure here is logged and swallowed: the account exists and can be
        verified later, and failing the whole sign-up because a mail server
        hiccuped would be a worse outcome than an email the user can request
        again.
        """
        try:
            async with httpx.AsyncClient(timeout=settings.identity_timeout_seconds) as client:
                token = await self._access_token(client)
                response = await client.put(
                    f"{_admin_base()}/users/{subject_id}/execute-actions-email",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"client_id": settings.registration_redirect_client},
                    json=["VERIFY_EMAIL"],
                )
                if response.status_code not in (204, 200):
                    log.warning(
                        "keycloak_verification_email_failed", status=response.status_code
                    )
        except httpx.HTTPError as exc:
            log.warning("keycloak_verification_email_error", error=str(exc))

    async def delete_user(self, subject_id: str) -> bool:
        """Undo `create_user`.

        The compensating half of sign-up. Returns whether it succeeded, because
        the caller has to log the difference: a failure here leaves a login with
        no tenant behind it, which is recoverable but must be visible.
        """
        try:
            async with httpx.AsyncClient(timeout=settings.identity_timeout_seconds) as client:
                token = await self._access_token(client)
                response = await client.delete(
                    f"{_admin_base()}/users/{subject_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                return response.status_code in (204, 404)
        except httpx.HTTPError as exc:
            log.error("keycloak_delete_user_failed", subject_id=subject_id, error=str(exc))
            return False


_admin = KeycloakAdmin()


def get_admin() -> KeycloakAdmin:
    return _admin


def set_admin(admin: KeycloakAdmin) -> None:
    """Test seam. Sign-up is not worth a real Keycloak round trip per test."""
    global _admin
    _admin = admin
