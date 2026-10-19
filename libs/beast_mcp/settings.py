"""All configuration comes from the environment (a Kubernetes ConfigMap + Secret in production)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    server_name: str
    # Entra ID (or the dev issuer, which mints the same claim shape)
    issuer: str
    audience: str
    jwks_url: str
    auth_disabled: bool
    # OPA
    opa_url: str
    policy_disabled: bool
    env: str  # dev | staging | prod: OPA uses it to gate skills by lifecycle stage

    @classmethod
    def load(cls, server_name: str) -> "Settings":
        e = os.environ.get
        tenant = e("ENTRA_TENANT_ID", "")
        issuer = e("AUTH_ISSUER") or (f"https://login.microsoftonline.com/{tenant}/v2.0" if tenant else "")
        jwks = e("AUTH_JWKS_URL") or (f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys" if tenant else "")
        return cls(
            server_name=server_name,
            issuer=issuer,
            audience=e("AUTH_AUDIENCE", "api://beast-assist"),
            jwks_url=jwks,
            auth_disabled=e("AUTH_DISABLED", "0") == "1",
            opa_url=e("OPA_URL", "http://localhost:8181"),
            policy_disabled=e("POLICY_DISABLED", "0") == "1",
            env=e("BEAST_ENV", "dev"),
        )
