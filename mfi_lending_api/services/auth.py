"""Where the bearer token for the lending service comes from (DECISIONS D-005).

* ``static``: a fixed token from configuration, for the WireMock stub and
  development.
* ``service_account``: Keycloak client credentials, cached in memory until
  shortly before they expire. The service, not the person, is the actor in the
  lending service's records; Odoo's audit log still names the person.
* ``token_exchange``: the signed-in person's Keycloak token (put in the HTTP
  session at sign-in, never on the user record: access-keycloak K15), exchanged
  for one addressed to the lending service. The exchanged token is kept in the
  session until it expires. No token is ever written to the database.
"""

import threading
import time

import requests

from .config import secret
from .errors import LendingNotConfigured, LendingRefusal, LendingUnavailable

# Session key where the sign-in (TASKLIST LA-41) leaves the person's own token.
SUBJECT_TOKEN_KEY = "mfi_lending_subject_token"
EXCHANGED_TOKEN_KEY = "mfi_lending_exchanged_token"
EXPIRY_MARGIN = 30  # seconds: renew a token this long before it expires

_service_tokens = {}
_service_tokens_lock = threading.Lock()


def _post_token(cfg, data):
    try:
        response = requests.post(cfg.token_url, data=data,
                                 timeout=(cfg.connect_timeout, cfg.read_timeout))
    except requests.RequestException as error:
        raise LendingUnavailable(f"token endpoint: {type(error).__name__}") from None
    if response.status_code >= 500:
        raise LendingUnavailable(f"token endpoint answered {response.status_code}", response.status_code)
    if response.status_code != 200:
        # Keycloak's OAuth error; nothing personal in it, but keep only its code.
        try:
            error_code = response.json().get("error") or "token_refused"
        except ValueError:
            error_code = "token_refused"
        raise LendingRefusal(401, {"code": "unauthenticated", "detail": error_code})
    body = response.json()
    token = body.get("access_token")
    if not token:
        raise LendingUnavailable("token endpoint answered without a token")
    return token, time.time() + int(body.get("expires_in") or 60)


class StaticToken:
    def __init__(self, cfg):
        self.cfg = cfg

    def token(self):
        # The stub checks no token; a real service run on static mode needs one.
        return secret("static_token") or "stub"


class ServiceAccountToken:
    def __init__(self, cfg):
        self.cfg = cfg

    def token(self):
        client_secret = secret("client_secret")
        if not client_secret:
            raise LendingNotConfigured("the client secret (kapu_lending_client_secret in odoo.conf)")
        key = (self.cfg.token_url, self.cfg.client_id, self.cfg.audience)
        with _service_tokens_lock:
            cached = _service_tokens.get(key)
            if cached and cached[1] - EXPIRY_MARGIN > time.time():
                return cached[0]
        token, expires = _post_token(self.cfg, {
            "grant_type": "client_credentials",
            "client_id": self.cfg.client_id,
            "client_secret": client_secret,
            "audience": self.cfg.audience,
        })
        with _service_tokens_lock:
            _service_tokens[key] = (token, expires)
        return token


class TokenExchange:
    """RFC 8693 token exchange as the signed-in person (access-keycloak §7)."""

    def __init__(self, cfg, session):
        self.cfg = cfg
        self.session = session

    def token(self):
        if self.session is None:
            raise LendingNotConfigured("token exchange needs a signed-in person; it cannot run in the background")
        cached = self.session.get(EXCHANGED_TOKEN_KEY)
        if cached and cached.get("expires", 0) - EXPIRY_MARGIN > time.time():
            return cached["token"]
        subject = self.session.get(SUBJECT_TOKEN_KEY)
        if not subject:
            raise LendingRefusal(401, {"code": "unauthenticated", "detail": "no Keycloak sign-in in this session"})
        client_secret = secret("client_secret")
        if not client_secret:
            raise LendingNotConfigured("the client secret (kapu_lending_client_secret in odoo.conf)")
        token, expires = _post_token(self.cfg, {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": self.cfg.client_id,
            "client_secret": client_secret,
            "subject_token": subject,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": self.cfg.audience,
        })
        self.session[EXCHANGED_TOKEN_KEY] = {"token": token, "expires": expires}
        return token


def token_provider(cfg, session=None):
    if cfg.auth_mode == "service_account":
        return ServiceAccountToken(cfg)
    if cfg.auth_mode == "token_exchange":
        return TokenExchange(cfg, session)
    return StaticToken(cfg)


def clear_cached_tokens():
    """After a settings change: forget service-account tokens."""
    with _service_tokens_lock:
        _service_tokens.clear()
