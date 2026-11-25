"""The connection's settings: non-secret values in system parameters, secrets
only in odoo.conf or the environment, never in the database (DECISIONS D-005)."""

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from odoo.tools import config as odoo_config

from .errors import LendingNotConfigured

PREFIX = "mfi_lending_api."
AUTH_MODES = [
    ("static", "Static token (stub and development)"),
    ("service_account", "Service account (client credentials)"),
    ("token_exchange", "Token exchange as the signed-in person (production)"),
]
DEFAULT_CONNECT_TIMEOUT = 5
DEFAULT_READ_TIMEOUT = 15


def secret(name):
    """A secret from odoo.conf (``kapu_lending_<name>``) or the environment
    (``KAPU_LENDING_<NAME>``); never from the database."""
    key = f"kapu_lending_{name}"
    return odoo_config.get(key) or os.environ.get(key.upper()) or ""


@dataclass(frozen=True)
class LendingConfig:
    enabled: bool
    base_url: str
    auth_mode: str
    token_url: str
    client_id: str
    audience: str
    connect_timeout: int
    read_timeout: int
    stub_example: str
    skip_upload_transfer: bool
    upload_hosts: tuple

    @classmethod
    def load(cls, env):
        params = env["ir.config_parameter"].sudo()
        hosts = params.get_str(PREFIX + "upload_hosts")
        return cls(
            enabled=params.get_bool(PREFIX + "enabled"),
            base_url=(params.get_str(PREFIX + "base_url") or "").rstrip("/"),
            auth_mode=params.get_str(PREFIX + "auth_mode") or "static",
            token_url=params.get_str(PREFIX + "token_url"),
            client_id=params.get_str(PREFIX + "client_id"),
            audience=params.get_str(PREFIX + "audience") or "lending-service",
            connect_timeout=params.get_int(PREFIX + "connect_timeout") or DEFAULT_CONNECT_TIMEOUT,
            read_timeout=params.get_int(PREFIX + "read_timeout") or DEFAULT_READ_TIMEOUT,
            stub_example=params.get_str(PREFIX + "stub_example"),
            skip_upload_transfer=params.get_bool(PREFIX + "skip_upload_transfer"),
            upload_hosts=tuple(h.strip().lower() for h in hosts.split(",") if h.strip()),
        )

    def check(self):
        if not self.enabled:
            raise LendingNotConfigured("the connection is switched off")
        if not self.base_url:
            raise LendingNotConfigured("no service address")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise LendingNotConfigured("the service address is not a web address")
        if parsed.scheme == "http" and self.auth_mode != "static":
            # Real tokens travel only over TLS.
            raise LendingNotConfigured("the service address must use https outside the stub")
        if self.auth_mode not in dict(AUTH_MODES):
            raise LendingNotConfigured("an unknown sign-in mode")
        if self.auth_mode in ("service_account", "token_exchange") and not (self.token_url and self.client_id):
            raise LendingNotConfigured("the Keycloak token address and client id")
        return self

    @property
    def is_stub(self):
        return self.auth_mode == "static"
