"""Entra ID bearer tokens: RS256, checked against the tenant's JWKS for issuer, audience and expiry.

Scopes arrive in `scp` (delegated, space-separated) and app roles in `roles` (app-only tokens);
both are folded into one set so policy can ask for Tools.Read / Tools.Write either way."""
import time

import httpx
import jwt
from jwt import PyJWKSet

from .settings import Settings


class AuthError(Exception):
    pass


class TokenVerifier:
    def __init__(self, settings: Settings, ttl: int = 600):
        self.s, self.ttl = settings, ttl
        self._keys: PyJWKSet | None = None
        self._fetched = 0.0

    def _jwks(self, force: bool = False) -> PyJWKSet:
        if force or not self._keys or time.time() - self._fetched > self.ttl:
            r = httpx.get(self.s.jwks_url, timeout=5)
            r.raise_for_status()
            self._keys, self._fetched = PyJWKSet.from_dict(r.json()), time.time()
        return self._keys

    def _key(self, kid: str):
        for force in (False, True):  # a kid we have not seen means the tenant rotated keys: refetch once
            for k in self._jwks(force).keys:
                if k.key_id == kid:
                    return k.key
        raise AuthError("token signed with an unknown key")

    def _decode(self, token: str) -> dict:
        kid = jwt.get_unverified_header(token).get("kid", "")
        return jwt.decode(token, self._key(kid), algorithms=["RS256"], audience=self.s.audience,
                          issuer=self.s.issuer, options={"require": ["exp", "iss", "aud"]})

    def verify(self, authorization: str | None) -> dict:
        if self.s.auth_disabled:
            return {"sub": "dev", "oid": "dev", "permissions": {"Tools.Read", "Tools.Write"}}
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError("missing bearer token")
        token = authorization.split(None, 1)[1]
        try:
            claims = self._decode(token)
        except jwt.InvalidSignatureError:
            # the issuer may have re-keyed under a kid we already cached: refetch once, at most every 30 s
            if time.time() - self._fetched < 30:
                raise AuthError("invalid token: Signature verification failed") from None
            self._jwks(force=True)
            try:
                claims = self._decode(token)
            except jwt.PyJWTError as e:
                raise AuthError(f"invalid token: {e}") from None
        except jwt.PyJWTError as e:
            raise AuthError(f"invalid token: {e}") from None
        perms = set((claims.get("scp") or "").split()) | set(claims.get("roles") or [])
        claims["permissions"] = perms
        return claims
