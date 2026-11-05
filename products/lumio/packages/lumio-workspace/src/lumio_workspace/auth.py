"""Entra browser OIDC and resource-scoped API token validation."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from authlib.integrations.starlette_client import OAuth
from authlib.jose import JsonWebKey, JsonWebToken, KeySet
from authlib.jose.errors import JoseError
from mcp.server.auth.provider import AccessToken
from starlette.requests import Request

from .state import Actor, WorkspaceState


class AuthenticationError(Exception):
    pass


@dataclass(frozen=True)
class IdentityConfig:
    tenant_id: str
    issuer: str
    metadata_url: str
    audience: str
    pi_client_id: str
    browser_client_id: str
    browser_client_secret: str
    browser_redirect_uri: str

    @classmethod
    def from_env(cls) -> IdentityConfig:
        tenant_id = _required("LUMIO_WORKSPACE_TENANT_ID")
        issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        return cls(
            tenant_id=tenant_id,
            issuer=issuer,
            metadata_url=f"{issuer}/.well-known/openid-configuration",
            audience=_required("LUMIO_WORKSPACE_API_AUDIENCE"),
            pi_client_id=_required("LUMIO_WORKSPACE_PI_CLIENT_ID"),
            browser_client_id=_required("LUMIO_WORKSPACE_BROWSER_CLIENT_ID"),
            browser_client_secret=_required("LUMIO_WORKSPACE_BROWSER_CLIENT_SECRET"),
            browser_redirect_uri=_required("LUMIO_WORKSPACE_BROWSER_REDIRECT_URI"),
        )

    def __post_init__(self) -> None:
        for value in (
            self.tenant_id,
            self.audience,
            self.pi_client_id,
            self.browser_client_id,
            self.browser_client_secret,
        ):
            if not value:
                raise ValueError("identity configuration values must not be empty")
        for url in (self.issuer, self.metadata_url, self.browser_redirect_uri):
            if not url.startswith("https://"):
                raise ValueError("Entra and browser callback URLs must use HTTPS")


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"missing required configuration: {name}")
    return value


class LocalTokenVerifier:
    """Authenticate only current, purpose-bound local API credentials."""

    def __init__(self, state: WorkspaceState) -> None:
        self.state = state

    async def verify_token(self, token: str) -> AccessToken | None:
        credential = self.state.authenticate_local_credential(token, purpose="api")
        if credential is None:
            return None
        return AccessToken(
            token=token,
            client_id=f"local:{credential.actor.object_id}",
            scopes=["Knowledge.Read"],
            expires_at=credential.expires_at,
            resource="lumio-workspace",
            subject=credential.actor.object_id,
            claims={
                "tid": credential.actor.tenant_id,
                "oid": credential.actor.object_id,
                "credential_id": credential.credential_id,
            },
        )


class EntraTokenVerifier:
    """Validate v2 Entra access tokens for the configured API and Pi client."""

    def __init__(self, config: IdentityConfig, *, key_set: KeySet | None = None) -> None:
        self.config = config
        self._key_set = key_set
        self._lock = asyncio.Lock()
        self._last_forced_refresh: float | None = None
        self._jwt = JsonWebToken(["RS256"])

    async def _load_key_set(self, *, force_refresh: bool = False) -> KeySet:
        if self._key_set is not None and not force_refresh:
            return self._key_set
        async with self._lock:
            if self._key_set is not None and not force_refresh:
                return self._key_set
            now = time.monotonic()
            if (
                self._key_set is not None
                and self._last_forced_refresh is not None
                and now - self._last_forced_refresh < 60
            ):
                return self._key_set
            async with httpx.AsyncClient(timeout=10) as client:
                metadata_response = await client.get(self.config.metadata_url)
                metadata_response.raise_for_status()
                metadata = metadata_response.json()
                if metadata.get("issuer") != self.config.issuer:
                    raise ValueError("OIDC metadata issuer mismatch")
                jwks_response = await client.get(metadata["jwks_uri"])
                jwks_response.raise_for_status()
                self._key_set = JsonWebKey.import_key_set(jwks_response.json())
            if force_refresh:
                self._last_forced_refresh = now
        return self._key_set

    def _verify_with_key_set(self, token: str, key_set: KeySet) -> AccessToken | None:
        claims = self._jwt.decode(
            token,
            key_set,
            claims_options={
                "iss": {"essential": True, "value": self.config.issuer},
                "aud": {"essential": True, "value": self.config.audience},
                "exp": {"essential": True},
                "iat": {"essential": True},
                "tid": {"essential": True, "value": self.config.tenant_id},
                "oid": {"essential": True},
                "azp": {"essential": True, "value": self.config.pi_client_id},
                "scp": {"essential": True},
            },
        )
        claims.validate()
        scopes = claims["scp"].split()
        if not claims["oid"] or "Knowledge.Read" not in scopes:
            return None
        return AccessToken(
            token=token,
            client_id=claims["azp"],
            scopes=scopes,
            expires_at=claims["exp"],
            resource=self.config.audience,
            subject=claims["oid"],
            claims=dict(claims),
        )

    @staticmethod
    def _unknown_kid(token: str, key_set: KeySet) -> bool:
        try:
            header_segment = token.split(".", 1)[0]
            padded = header_segment + "=" * (-len(header_segment) % 4)
            header = json.loads(base64.urlsafe_b64decode(padded))
            kid = header.get("kid")
        except (TypeError, ValueError):
            return False
        return isinstance(kid, str) and bool(kid) and all(
            key.as_dict().get("kid") != kid for key in key_set.keys
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key_set = await self._load_key_set()
            for refreshed in (False, True):
                try:
                    return self._verify_with_key_set(token, key_set)
                except (JoseError, KeyError, ValueError):
                    if refreshed or not self._unknown_kid(token, key_set):
                        return None
                    refreshed_key_set = await self._load_key_set(force_refresh=True)
                    if refreshed_key_set is key_set:
                        return None
                    key_set = refreshed_key_set
        except (JoseError, httpx.HTTPError, KeyError, TypeError, ValueError):
            return None
        return None


class EntraBrowserAuth:
    """Confidential-web OIDC with PKCE; no API bearer token is accepted here."""

    def __init__(self, config: IdentityConfig) -> None:
        self.config = config
        self._oauth = OAuth()
        self._oauth.register(
            "entra",
            client_id=config.browser_client_id,
            client_secret=config.browser_client_secret,
            server_metadata_url=config.metadata_url,
            client_kwargs={"scope": "openid profile", "code_challenge_method": "S256"},
        )

    async def login(self, request: Request) -> Any:
        return await self._oauth.entra.authorize_redirect(request, self.config.browser_redirect_uri)

    async def authenticate_callback(self, request: Request) -> Actor:
        try:
            token = await self._oauth.entra.authorize_access_token(request)
            claims = token["userinfo"]
            if claims.get("tid") != self.config.tenant_id or not claims.get("oid"):
                raise AuthenticationError("browser identity is not in the configured tenant")
            return Actor(tenant_id=claims["tid"], object_id=claims["oid"])
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("browser sign-in failed") from exc
