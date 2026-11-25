"""Answer like the WireMock stub, from its own mappings (fixtures/lending.json,
a copy of Requirements/lending.json), without a network."""

import json
import re
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from odoo.tests import TransactionCase

from ..services.client import LendingClient, TransportResponse
from ..services.config import PREFIX

FIXTURE = Path(__file__).parent / "fixtures" / "lending.json"
MAPPINGS = json.loads(FIXTURE.read_text())["mappings"]
STUB_URL = "http://stub.test"


def operation_of(mapping):
    return mapping["name"].split(":", 1)[0]


class StubTransport:
    """``examples`` picks a named answer per operation, as X-Stub-Example would:
    ``{"createClient": "client_already_exists"}``. Every call is recorded."""

    def __init__(self, examples=None):
        self.examples = dict(examples or {})
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        if method == "PUT":
            return TransportResponse(200, {}, b"")
        path = urlparse(url).path
        candidates = [m for m in MAPPINGS
                      if m["request"]["method"] == method
                      and re.fullmatch(m["request"]["urlPathPattern"], path)]
        assert candidates, f"no stub mapping for {method} {path}"
        sent = {k.lower(): v for k, v in headers.items()}
        example = sent.get("x-stub-example") or self.examples.get(operation_of(candidates[0]))
        if example:
            sent["x-stub-example"] = example

        def matches(mapping):
            for name, rule in (mapping["request"].get("headers") or {}).items():
                value = sent.get(name.lower())
                if rule.get("absent") and value is not None:
                    return False
                if "equalTo" in rule and value != rule["equalTo"]:
                    return False
            return True

        chosen = sorted((m for m in candidates if matches(m)), key=lambda m: m.get("priority", 5))
        assert chosen, f"no stub answer for {method} {path} {example}"
        response = chosen[0]["response"]
        return TransportResponse(response["status"], dict(response.get("headers") or {}),
                                 json.dumps(response.get("jsonBody", {})).encode())


class LendingCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The command log writes on a cursor of its own: in tests it must wrap
        # the test's transaction instead of committing to the database.
        cls.enterClassContext(cls.registry_test_mode())
        params = cls.env["ir.config_parameter"].sudo()
        params.set_bool(PREFIX + "enabled", True)
        params.set_str(PREFIX + "base_url", STUB_URL)
        params.set_str(PREFIX + "auth_mode", "static")
        params.set_str(PREFIX + "upload_hosts", "vault.example.invalid")

    def stub(self, **examples):
        """Patch the network for this test; returns the transport to inspect calls."""
        transport = StubTransport(examples)
        patcher = patch.object(LendingClient, "transport", staticmethod(transport))
        patcher.start()
        self.addCleanup(patcher.stop)
        return transport

    def client(self):
        return LendingClient(self.env)
