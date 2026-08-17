"""Teach an existing realm to ask for a one-time code.

`realm-dev.json` describes a realm that has never been created. Keycloak's
`--import-realm` skips a realm that already exists, so editing that file changes
nothing on any environment that has ever been started — including production,
where the realm is months old. Anything added to a live realm has to be added
through the admin API, which is what this does.

Idempotent, and safe to run against a realm that is already configured: every
step checks before it writes. Run it after deploying a change to the flow, and
again whenever you are not sure.

    docker compose exec api .venv/bin/python -m scripts.configure_step_up

What it sets up:

    a one-time code policy          so a code can be enrolled at all
    an `acr` to level mapping       so "typed a code" becomes a number
    a browser flow in two steps     password always, code only when asked for
    CONFIGURE_TOTP as an action     offered, never forced

The flow is the point. A normal sign-in never sees the second step; it appears
only when a client asks to reach level two, which the admin application does
when the API answers `STEP_UP_REQUIRED`. A club president who never touches the
card gateway is never asked for a code.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx

REALM = os.environ.get("KEYCLOAK_REALM", "football-os")
BASE = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080")
ADMIN_USER = os.environ.get("KEYCLOAK_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "admin")

TOP_FLOW = "browser-stepup"
FORMS_FLOW = "browser-stepup-forms"
PASSWORD_FLOW = "browser-stepup-password"
OTP_FLOW = "browser-stepup-otp"

# Fifteen minutes, matching `STEP_UP_MAX_AGE` in app/api/deps.py. Keycloak's
# window must not be the longer of the two: it would hand back a token the API
# then refuses, sending somebody round the loop with nothing they can do.
STEP_UP_MAX_AGE_SECONDS = "900"
SESSION_MAX_AGE_SECONDS = "36000"


class Keycloak:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}

    async def get(self, path: str) -> Any:
        response = await self.client.get(f"{BASE}{path}", headers=self.headers)
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, body: dict) -> httpx.Response:
        return await self.client.post(f"{BASE}{path}", headers=self.headers, json=body)

    async def put(self, path: str, body: dict) -> httpx.Response:
        response = await self.client.put(f"{BASE}{path}", headers=self.headers, json=body)
        response.raise_for_status()
        return response


async def sign_in(client: httpx.AsyncClient) -> str:
    response = await client.post(
        f"{BASE}/realms/master/protocol/openid-connect/token",
        data={
            "client_id": "admin-cli",
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
            "grant_type": "password",
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]


async def set_realm_settings(kc: Keycloak) -> None:
    realm = await kc.get(f"/admin/realms/{REALM}")
    attributes = dict(realm.get("attributes") or {})
    attributes["acr.loa.map"] = json.dumps({"1": 1, "2": 2})

    realm.update(
        {
            "otpPolicyType": "totp",
            "otpPolicyAlgorithm": "HmacSHA1",
            "otpPolicyDigits": 6,
            "otpPolicyPeriod": 30,
            # One step either side, for a phone whose clock has drifted.
            "otpPolicyLookAheadWindow": 1,
            "attributes": attributes,
        }
    )
    await kc.put(f"/admin/realms/{REALM}", realm)
    print("realm: one-time code policy and acr mapping set")


async def ensure_required_action(kc: Keycloak) -> None:
    existing = await kc.get(f"/admin/realms/{REALM}/authentication/required-actions")
    if any(action["alias"] == "CONFIGURE_TOTP" for action in existing):
        print("required action: already offered")
        return
    available = await kc.get(
        f"/admin/realms/{REALM}/authentication/unregistered-required-actions"
    )
    for action in available:
        if action.get("providerId") == "CONFIGURE_TOTP":
            await kc.post(
                f"/admin/realms/{REALM}/authentication/register-required-action", action
            )
            print("required action: CONFIGURE_TOTP registered")
            return
    print("required action: CONFIGURE_TOTP not available on this server", file=sys.stderr)


async def flow_exists(kc: Keycloak, alias: str) -> bool:
    flows = await kc.get(f"/admin/realms/{REALM}/authentication/flows")
    return any(flow["alias"] == alias for flow in flows)


async def build_flow(kc: Keycloak) -> None:
    if await flow_exists(kc, TOP_FLOW):
        print(f"flow: {TOP_FLOW} already present, leaving it alone")
        return

    await kc.post(
        f"/admin/realms/{REALM}/authentication/flows",
        {
            "alias": TOP_FLOW,
            "description": (
                "Browser sign-in, with a one-time code when a client asks for level 2"
            ),
            "providerId": "basic-flow",
            "topLevel": True,
            "builtIn": False,
        },
    )

    async def add_execution(flow: str, provider: str, requirement: str) -> str:
        await kc.post(
            f"/admin/realms/{REALM}/authentication/flows/{flow}/executions/execution",
            {"provider": provider},
        )
        executions = await kc.get(
            f"/admin/realms/{REALM}/authentication/flows/{flow}/executions"
        )
        added = [e for e in executions if e.get("providerId") == provider][-1]
        added["requirement"] = requirement
        await kc.put(f"/admin/realms/{REALM}/authentication/flows/{flow}/executions", added)
        return added["id"]

    async def add_subflow(parent: str, alias: str, description: str, requirement: str) -> None:
        await kc.post(
            f"/admin/realms/{REALM}/authentication/flows/{parent}/executions/flow",
            {
                "alias": alias,
                "description": description,
                "provider": "registration-page-form",
                "type": "basic-flow",
            },
        )
        executions = await kc.get(
            f"/admin/realms/{REALM}/authentication/flows/{parent}/executions"
        )
        added = next(e for e in executions if e.get("displayName") == alias)
        added["requirement"] = requirement
        await kc.put(f"/admin/realms/{REALM}/authentication/flows/{parent}/executions", added)

    await add_execution(TOP_FLOW, "auth-cookie", "ALTERNATIVE")
    await add_execution(TOP_FLOW, "identity-provider-redirector", "ALTERNATIVE")
    await add_subflow(TOP_FLOW, FORMS_FLOW, "Password, then a code if asked for", "ALTERNATIVE")

    await add_subflow(FORMS_FLOW, PASSWORD_FLOW, "Level 1: who are you", "CONDITIONAL")
    await add_subflow(FORMS_FLOW, OTP_FLOW, "Level 2: prove it again", "CONDITIONAL")

    level_one = await add_execution(
        PASSWORD_FLOW, "conditional-level-of-authentication", "REQUIRED"
    )
    await add_execution(PASSWORD_FLOW, "auth-username-password-form", "REQUIRED")
    level_two = await add_execution(OTP_FLOW, "conditional-level-of-authentication", "REQUIRED")
    await add_execution(OTP_FLOW, "auth-otp-form", "REQUIRED")

    await kc.post(
        f"/admin/realms/{REALM}/authentication/executions/{level_one}/config",
        {
            "alias": "loa-level-1",
            "config": {
                "loa-condition-level": "1",
                "loa-max-age": SESSION_MAX_AGE_SECONDS,
            },
        },
    )
    await kc.post(
        f"/admin/realms/{REALM}/authentication/executions/{level_two}/config",
        {
            "alias": "loa-level-2",
            "config": {
                "loa-condition-level": "2",
                "loa-max-age": STEP_UP_MAX_AGE_SECONDS,
            },
        },
    )
    print(f"flow: {TOP_FLOW} built")


async def use_flow(kc: Keycloak) -> None:
    realm = await kc.get(f"/admin/realms/{REALM}")
    if realm.get("browserFlow") == TOP_FLOW:
        print("realm: already signing in through the step-up flow")
        return
    realm["browserFlow"] = TOP_FLOW
    await kc.put(f"/admin/realms/{REALM}", realm)
    print(f"realm: browser sign-in now uses {TOP_FLOW}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        kc = Keycloak(client, await sign_in(client))
        await set_realm_settings(kc)
        await ensure_required_action(kc)
        await build_flow(kc)
        await use_flow(kc)
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
