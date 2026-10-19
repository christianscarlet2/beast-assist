"""JWKS caching and rotation: a new key is picked up without a restart."""
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKSet
from jwt.algorithms import RSAAlgorithm

from beast_mcp.auth import AuthError, TokenVerifier
from beast_mcp.settings import Settings

S = Settings(server_name="t", issuer="iss", audience="aud", jwks_url="x", auth_disabled=False,
             opa_url="", policy_disabled=True, env="dev")


def keypair(kid):
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return k, RSAAlgorithm.to_jwk(k.public_key(), as_dict=True) | {"kid": kid, "alg": "RS256"}


def tok(key, kid):
    return "Bearer " + jwt.encode({"iss": "iss", "aud": "aud", "exp": int(time.time()) + 60, "roles": ["Tools.Read"]},
                                  key, algorithm="RS256", headers={"kid": kid})


def verifier(published):
    v = TokenVerifier(S)
    fetches = []

    def fake(force=False):
        if force or v._keys is None:
            fetches.append(1)
            v._keys, v._fetched = PyJWKSet.from_dict({"keys": list(published)}), time.time()
        return v._keys
    v._jwks = fake
    return v, fetches


def test_new_kid_triggers_one_refetch():
    k1, j1 = keypair("a")
    k2, j2 = keypair("b")
    published = [j1]
    v, fetches = verifier(published)
    assert v.verify(tok(k1, "a"))["permissions"] == {"Tools.Read"}
    published[:] = [j2]                       # the issuer rotated
    assert v.verify(tok(k2, "b"))
    assert len(fetches) == 2


def test_same_kid_new_key_recovers_after_cooldown():
    k1, j1 = keypair("same")
    k2, j2 = keypair("same")
    published = [j1]
    v, fetches = verifier(published)
    v.verify(tok(k1, "same"))
    published[:] = [j2]
    v._fetched -= 60                          # past the 30 s refetch cooldown
    assert v.verify(tok(k2, "same"))


def test_forged_token_still_refused():
    k1, j1 = keypair("a")
    forger, _ = keypair("a")
    v, _ = verifier([j1])
    v.verify(tok(k1, "a"))
    try:
        v.verify(tok(forger, "a"))
        raise AssertionError("forged token accepted")
    except AuthError as e:
        assert "Signature verification failed" in str(e)
