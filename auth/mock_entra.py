"""Dev token issuer with Entra ID's shape, for running the platform without an Azure tenant.

Serves the same endpoints the servers read in production:
    GET  /{tenant}/v2.0/.well-known/openid-configuration
    GET  /{tenant}/discovery/v2.0/keys           (JWKS)
    POST /{tenant}/oauth2/v2.0/token             client_credentials -> RS256 access token with roles,
                                                  or a dev shortcut: {"scp": "...", "oid": "..."}
Point AUTH_ISSUER / AUTH_JWKS_URL here locally; in Azure set ENTRA_TENANT_ID and delete this service.
"""
import hashlib
import os
import time
import uuid

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException
from jwt.algorithms import RSAAlgorithm

TENANT = os.environ.get("MOCK_TENANT", "beast-dev-tenant")
BASE = os.environ.get("MOCK_BASE", "http://localhost:8400").rstrip("/")
AUDIENCE = os.environ.get("AUTH_AUDIENCE", "api://beast-assist")
# client_id -> (secret, app roles). Mirrors app registrations: the agent may read and write, the eval
# runner may only read, the CI publisher may only upload skills.
CLIENTS = {
    "beast-agent": (os.environ.get("MOCK_AGENT_SECRET", "dev-agent-secret"), ["Tools.Read", "Tools.Write"]),
    "beast-evals": (os.environ.get("MOCK_EVALS_SECRET", "dev-evals-secret"), ["Tools.Read"]),
    "beast-publisher": (os.environ.get("MOCK_PUBLISHER_SECRET", "dev-publisher-secret"), ["Skills.Publish"]),
}
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# like Entra, a new key gets a new kid (here: a thumbprint), so verifiers notice a rotation
KID = hashlib.sha256(_key.public_key().public_bytes(serialization.Encoding.DER,
                     serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()[:16]
_pem = _key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
_jwk = RSAAlgorithm.to_jwk(_key.public_key(), as_dict=True) | {"kid": KID, "use": "sig", "alg": "RS256"}

app = FastAPI(title="mock-entra")
ISS = f"{BASE}/{TENANT}/v2.0"


def mint(sub: str, oid: str, roles: list[str] | None = None, scp: str = "", ttl: int = 3600) -> str:
    now = int(time.time())
    claims = {"iss": ISS, "aud": AUDIENCE, "sub": sub, "oid": oid, "tid": TENANT, "iat": now, "nbf": now,
              "exp": now + ttl, "ver": "2.0", "azp": sub}
    if roles:
        claims["roles"] = roles
    if scp:
        claims["scp"] = scp
    return jwt.encode(claims, _pem, algorithm="RS256", headers={"kid": KID})


@app.get(f"/{TENANT}/v2.0/.well-known/openid-configuration")
def discovery():
    return {"issuer": ISS, "jwks_uri": f"{BASE}/{TENANT}/discovery/v2.0/keys",
            "token_endpoint": f"{BASE}/{TENANT}/oauth2/v2.0/token", "id_token_signing_alg_values_supported": ["RS256"]}


@app.get(f"/{TENANT}/discovery/v2.0/keys")
def keys():
    return {"keys": [_jwk]}


@app.post(f"/{TENANT}/oauth2/v2.0/token")
def token(grant_type: str = Form(...), client_id: str = Form(...), client_secret: str = Form(...),
          scope: str = Form("")):
    if grant_type != "client_credentials":
        raise HTTPException(400, "unsupported_grant_type")
    secret, roles = CLIENTS.get(client_id, (None, []))
    if secret is None or client_secret != secret:
        raise HTTPException(401, "invalid_client")
    return {"token_type": "Bearer", "expires_in": 3600,
            "access_token": mint(client_id, str(uuid.uuid5(uuid.NAMESPACE_DNS, client_id)), roles=roles)}


@app.get("/healthz")
def healthz():
    return {"ok": True}
