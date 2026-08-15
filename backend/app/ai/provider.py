"""AI provider port and the Anthropic adapter.

Same pattern as payments: nothing outside this module imports `anthropic`, so
the model vendor is a swappable detail rather than a dependency of the CMS.

**Where the key lives.** One platform-held API key serves every tenant, read
from the environment (and in production from a secret manager). It is
deliberately *not* stored in the database and not editable through the
super-admin UI: a provider secret in the application database is one dump away
from disclosure, and it would appear in backups, replicas and any tenant export
bug. What the platform *does* control per tenant is the policy around it —
whether the feature is on, and how much of it a tenant may use. See
docs/architecture/07-entitlements.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from app.core.config import settings
from app.core.errors import DomainError

log = structlog.get_logger(__name__)


class AiUnavailable(DomainError):
    code, status = "AI_UNAVAILABLE", 503
    default_message = "The writing assistant is temporarily unavailable."


class AiRefused(DomainError):
    code, status = "AI_REFUSED", 422
    default_message = (
        "The assistant declined to rewrite this text. Edit it manually, or "
        "rephrase and try again."
    )


@dataclass(frozen=True, slots=True)
class AiRequest:
    system: str
    user: str
    schema: dict[str, Any]
    max_tokens: int = 4096
    # Rewriting is not a reasoning-heavy task; low effort keeps latency and
    # cost down without hurting quality on this workload.
    effort: str = "low"


@dataclass(frozen=True, slots=True)
class AiResult:
    output: dict[str, Any]
    input_tokens: int
    output_tokens: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class AiProvider(Protocol):
    async def complete(self, request: AiRequest) -> AiResult: ...

    @property
    def is_configured(self) -> bool: ...


class AnthropicProvider:
    """Anthropic adapter.

    Uses structured outputs so the model returns a validated block document
    rather than prose we would have to parse. That is a correctness property,
    not a convenience: the CMS body is a typed block list, and free text coming
    back from a model would have to be re-parsed into blocks — exactly the step
    where malformed or unexpected content could slip in.
    """

    def __init__(self) -> None:
        self._client: Any | None = None

    @property
    def is_configured(self) -> bool:
        return bool(settings.anthropic_api_key.get_secret_value())

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                timeout=settings.ai_timeout_seconds,
                max_retries=2,
            )
        return self._client

    async def complete(self, request: AiRequest) -> AiResult:
        # Checked before the SDK is even imported, so a platform running
        # without a key gets a clean 503 rather than an import error.
        if not self.is_configured:
            raise AiUnavailable("No AI provider is configured for this platform.")

        import anthropic

        client = self._get_client()
        try:
            response = await client.messages.create(
                model=settings.ai_model,
                max_tokens=request.max_tokens,
                system=request.system,
                output_config={
                    "effort": request.effort,
                    "format": {"type": "json_schema", "schema": request.schema},
                },
                messages=[{"role": "user", "content": request.user}],
            )
        except anthropic.RateLimitError as exc:
            # The platform's shared key is saturated. This is our capacity
            # problem, not the club's mistake — say so plainly.
            log.warning("ai_rate_limited")
            raise AiUnavailable(
                "The writing assistant is busy. Try again in a moment."
            ) from exc
        except anthropic.APIStatusError as exc:
            log.error("ai_api_error", status=exc.status_code, type=exc.type)
            raise AiUnavailable() from exc
        except anthropic.APIConnectionError as exc:
            log.error("ai_connection_error")
            raise AiUnavailable() from exc

        # A refusal arrives as a normal 200 with an empty or partial body, so
        # this must be checked before reading content.
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            log.info("ai_refused", category=category)
            raise AiRefused()

        if response.stop_reason == "max_tokens":
            raise AiUnavailable(
                "That article is too long for the assistant to rewrite in one go. "
                "Try polishing a section at a time."
            )

        text = next((block.text for block in response.content if block.type == "text"), None)
        if not text:
            raise AiUnavailable()

        try:
            output = json.loads(text)
        except json.JSONDecodeError as exc:
            # Structured outputs make this near-impossible; treating it as a
            # provider failure rather than crashing keeps the editor working.
            log.error("ai_output_not_json")
            raise AiUnavailable() from exc

        return AiResult(
            output=output,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )


_provider: AiProvider = AnthropicProvider()


def get_provider() -> AiProvider:
    return _provider


def set_provider(provider: AiProvider) -> None:
    """Test seam."""
    global _provider
    _provider = provider
