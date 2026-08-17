"""Application settings.

Everything is environment-driven. Nothing here has a production-safe default:
if a value matters in production it must be supplied explicitly, so a missing
variable fails at startup rather than silently running with a dev value.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    secret_key: SecretStr = SecretStr("dev-only-secret-not-for-any-other-use")

    api_prefix: str = "/api/v1"
    # `NoDecode`, because pydantic-settings parses a list-typed field from the
    # environment as JSON *before* any validator runs. A comma-separated value
    # — the obvious thing to write, and what the validator below exists to
    # accept — makes the whole application fail to start, which reads as the
    # API being down rather than as a malformed setting.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            # The platform host serves both the marketing site and the admin
            # application, so it is the origin every authenticated call now
            # comes from.
            "http://footbola.localhost",
            "http://admin.footbola.localhost",
            "http://localhost:5173",
        ]
    )

    # --- Database -----------------------------------------------------------
    # Runtime role: RLS applies, no BYPASSRLS, no DDL.
    database_url: str = (
        "postgresql+asyncpg://app_runtime:dev_app_runtime@localhost:5432/footbola"
    )
    # Platform role: BYPASSRLS. Only reachable through platform_session().
    database_platform_url: str = (
        "postgresql+asyncpg://app_platform:dev_app_platform@localhost:5432/footbola"
    )
    # Migrator role: owns the schema. Sync driver, used by Alembic only.
    database_migrator_url: str = (
        "postgresql+psycopg://app_migrator:dev_app_migrator@localhost:5432/footbola"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_echo: bool = False

    redis_url: str = "redis://localhost:6379/0"

    # --- Identity -----------------------------------------------------------
    oidc_issuer: str = "http://keycloak:8080/realms/football-os"
    # The issuer as it appears in tokens minted through the browser-facing URL.
    # Keycloak issues `iss` based on the hostname the browser used, so in
    # development the container-internal and public issuers differ.
    oidc_public_issuer: str = "http://auth.footbola.localhost/realms/football-os"
    oidc_audience: str = "football-os-api"
    oidc_jwks_cache_seconds: int = 600

    # The confidential client used to create logins during sign-up. It holds
    # exactly one realm-management role, `manage-users` — never realm-admin.
    registration_client_id: str = "footbola-registration"
    registration_client_secret: SecretStr = SecretStr("dev-only-registration-secret")
    # The client the verification link returns to.
    registration_redirect_client: str = "admin-web"
    # Whether a new club has to answer a verification email before it can sign
    # in. On by default: without it, anyone can register a club under an
    # address they do not control, and the club's own name is the thing being
    # claimed.
    #
    # It is a separate switch rather than "off when SMTP is unset", because an
    # instance whose mail quietly breaks must not quietly stop verifying — the
    # symptom would be new accounts working better than before. Turn it off
    # deliberately, while standing a platform up, and turn it back on with the
    # first working mailbox.
    require_email_verification: bool = True
    # The public client a club's supporters sign in through. Named here because
    # every verified club domain has to be added to its redirect list.
    supporter_client_id: str = "supporter-web"
    # A second service account, holding `manage-clients` and nothing else. Kept
    # apart from the registration account so a flaw in public sign-up cannot
    # reconfigure the realm, and a flaw here cannot mint logins.
    domains_client_id: str = "footbola-domains"
    domains_client_secret: SecretStr = SecretStr("dev-only-domains-secret")
    # Where a new club's website lives until it brings its own domain:
    # `<slug>.<this>`. One subdomain per club, issued at sign-up, so a club has
    # a working address the moment it registers.
    public_site_domain: str = "localhost"
    identity_timeout_seconds: float = 15.0
    # `supporter-web` is the club sites' own client. A token from it carries no
    # tenant membership and reaches only the supporter's own account routes —
    # the permission checks decide that, not this list, which exists to reject
    # tokens minted for something else entirely.
    # `NoDecode` for the same reason as `cors_origins` above.
    oidc_allowed_clients: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "admin-web",
            "super-admin",
            "supporter-web",
            "public-web",
            "scanner",
        ]
    )

    # Where this API answers from, as the outside world reaches it. Needed
    # because a payment gateway redirects a buyer's browser back to us and can
    # only be given an absolute address — one it will refuse if it does not
    # match what the merchant registered, so this is not merely cosmetic.
    api_public_url: str = "http://api.footbola.localhost"

    # Which `acr` values count as a second factor. Keycloak maps these to
    # steps in its authentication flow — the realm's `acr.loa.map` says which
    # level demands a one-time code, and this says which levels we accept as
    # having supplied one. A list because a realm may define more than one
    # level above the password, and all of them are stronger than none.
    step_up_acr_values: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["2"])

    permission_cache_seconds: int = 60
    entitlement_cache_seconds: int = 300

    # On-demand cache purge for the public site. A shared secret rather than
    # a signed request: the endpoint is on the internal network, takes no
    # user input beyond a hostname, and only ever discards a cache entry.
    public_web_internal_url: str = "http://public-web:3000"
    revalidate_secret: SecretStr = SecretStr("dev-only-revalidate-secret")

    # --- AI writing assistant ----------------------------------------------
    # One platform-held key serves every tenant. Deliberately environment-only
    # (secret manager in production) and never stored in the database: a
    # provider secret in the app database is one dump, backup or export bug
    # away from disclosure. Per-tenant *policy* lives in entitlements.
    anthropic_api_key: SecretStr = SecretStr("")
    ai_model: str = "claude-opus-5"
    ai_timeout_seconds: float = 60.0

    # --- API-Football (api-sports.io) ---------------------------------------
    # Same shape as the assistant key above, and for the same reason: one
    # platform-held key serves every club, so the secret is environment-only
    # and the *policy* — who may sync, and how often — lives in entitlements.
    #
    # The shared key also means a shared rate limit. Every call any club causes
    # comes out of one daily allowance, which is why sync is scheduled and
    # budgeted rather than fired whenever a page is rendered.
    api_football_key: SecretStr = SecretStr("")
    api_football_base_url: str = "https://v3.football.api-sports.io"
    api_football_timeout_seconds: float = 20.0

    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_use_tls: bool = False
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")

    # Which way club email leaves. SMTP is what a club already has; Mailgun is
    # written and stays unreachable until a key exists, so an unpaid account
    # cannot start sending because a library happened to be installed.
    email_provider: str = "SMTP"
    mailgun_api_key: SecretStr = SecretStr("")
    mailgun_domain: str = ""
    mailgun_base_url: str = "https://api.eu.mailgun.net/v3"

    # What a club's mail says it is from, until the club sets its own.
    email_from_name: str = "TeamSport360"
    email_from_address: str = "no-reply@footbola.local"

    # Blank for Amazon S3 itself, where boto resolves the regional endpoint
    # from `s3_region`. Set for everything else — MinIO, OpenStack/Ceph,
    # Cloudflare R2 — which is most of what a European club or council is
    # actually allowed to use.
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "dev_minio_access"
    s3_secret_key: SecretStr = SecretStr("dev_minio_secret_key")
    s3_bucket: str = "footbola-dev"
    s3_region: str = "us-east-1"
    # `path` puts the bucket in the URL path (`host/bucket/key`) and `virtual`
    # in the hostname (`bucket.host/key`). MinIO and most OpenStack gateways
    # need path; Amazon and R2 want virtual. `auto` lets boto decide, which it
    # does correctly for Amazon and inconsistently for everyone else — so this
    # is worth stating rather than discovering through 400s.
    s3_addressing_style: Literal["auto", "path", "virtual"] = "path"
    # Where a *browser* reaches an object: the base a storage key hangs
    # directly off, bucket included where the provider expects it in the path.
    #
    # Separate from the endpoint above, and not derived from it. In
    # development the API talks to `minio:9000` on the Docker network while the
    # browser needs a host it can resolve; in production this is often a CDN
    # domain in front of the bucket, with no bucket in the URL at all.
    s3_public_url: str = "http://files.footbola.localhost/footbola-dev"

    # Where a visit came from. An optional MaxMind-format database — DB-IP's
    # free City Lite works and needs no account. Absent, geography is simply
    # not recorded and every other number is unaffected: analytics must never
    # depend on a 60MB file being present.
    geoip_database_path: str = "/app/data/geoip.mmdb"
    geoip_download_url: str = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"

    seed_demo_data: bool = True

    @field_validator(
        "cors_origins", "oidc_allowed_clients", "step_up_acr_values", mode="before"
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """A comma-separated list, or a JSON array.

        Both, because both are things people write in a `.env` and neither is
        wrong. JSON is what pydantic-settings used to insist on, so it exists
        in files already; commas are what anyone writes who has not read that
        far. Guessing between them costs one `startswith`.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            import json

            try:
                return json.loads(text)
            except ValueError:
                # Fall through: a malformed array is more likely a stray
                # bracket than a JSON document, and the comma split gives a
                # better error than a JSON parser's.
                pass
        return [item.strip() for item in text.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def accepted_issuers(self) -> tuple[str, ...]:
        return tuple({self.oidc_issuer, self.oidc_public_issuer})


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
