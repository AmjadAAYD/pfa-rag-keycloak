"""Verify Keycloak access tokens before deriving document roles."""

import json
from dataclasses import dataclass
from functools import cached_property
from urllib.request import urlopen

import jwt
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError, PyJWTError

from .corpus import KNOWN_ROLES


class InvalidAccessToken(ValueError):
    pass


class IdentityUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str
    username: str
    roles: frozenset[str]


class KeycloakVerifier:
    def __init__(self, issuer: str, audience: str):
        self.issuer = issuer.rstrip("/")
        self.audience = audience

    @cached_property
    def keys(self) -> jwt.PyJWKClient:
        discovery_url = f"{self.issuer}/.well-known/openid-configuration"
        expected_certs = f"{self.issuer}/protocol/openid-connect/certs"
        try:
            with urlopen(discovery_url, timeout=5) as response:
                discovery = json.load(response)
        except (OSError, ValueError) as error:
            raise IdentityUnavailable("Keycloak discovery is unavailable") from error
        if (
            not isinstance(discovery, dict)
            or discovery.get("issuer") != self.issuer
            or discovery.get("jwks_uri") != expected_certs
        ):
            raise IdentityUnavailable("Keycloak discovery does not match the configured issuer")
        return jwt.PyJWKClient(expected_certs, timeout=5)

    def check_ready(self) -> None:
        try:
            self.keys.get_signing_keys(refresh=True)
        except (PyJWTError, OSError, ValueError) as error:
            raise IdentityUnavailable("Keycloak signing keys are unavailable") from error

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
                raise InvalidAccessToken
            key = self.keys.get_signing_key(kid).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"],
                audience=self.audience, issuer=self.issuer,
                options={"require": ["iss", "aud", "sub", "exp", "iat", "typ"]},
            )
        except PyJWKClientConnectionError as error:
            raise IdentityUnavailable("Keycloak signing keys are unavailable") from error
        except (InvalidTokenError, PyJWKClientError, TypeError) as error:
            raise InvalidAccessToken from error
        except (PyJWTError, OSError, ValueError) as error:
            if isinstance(error, InvalidAccessToken):
                raise
            raise IdentityUnavailable("Keycloak signing keys are invalid or unavailable") from error

        subject = claims["sub"]
        if claims["typ"] != "Bearer" or not isinstance(subject, str) or not subject.strip():
            raise InvalidAccessToken
        resources = claims.get("resource_access")
        client = resources.get(self.audience) if isinstance(resources, dict) else None
        roles = client.get("roles") if isinstance(client, dict) else None
        recognized = (
            KNOWN_ROLES.intersection(role for role in roles if isinstance(role, str))
            if isinstance(roles, list) else frozenset()
        )
        username = claims.get("preferred_username")
        if not isinstance(username, str) or not username:
            username = subject
        return Principal(subject, username, recognized)
