"""The Kapu lending staff API, slice 1 (Requirements/kapu-lending.v1.yaml).

One method per operation. Writes take the ``Idempotency-Key`` from the caller
(the command log keeps it, so a retry sends the same key: DECISIONS D-006);
PATCH and submit take the ``ETag`` of a fresh read (D-007). Answers come back
as ``LendingResponse``; refusals and outages as the exceptions in ``errors``.

Logging carries the method, the path template, the status, the time and the
trace id: never a body, a name or a number (D-012).
"""

import json
import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlparse

import requests

from .auth import token_provider
from .config import LendingConfig
from .errors import LendingRefusal, LendingUnavailable

_logger = logging.getLogger(__name__)

JSON = "application/json"
MERGE_PATCH = "application/merge-patch+json"
PROBLEM = "application/problem+json"
UPLOAD_CONTENT_TYPES = ("image/jpeg", "image/png", "application/pdf")


@dataclass
class TransportResponse:
    status: int
    headers: dict
    content: bytes


def requests_transport(method, url, headers, body, timeout):
    """The real network. Tests swap ``LendingClient.transport`` for a fake."""
    try:
        response = requests.request(method, url, headers=headers, data=body, timeout=timeout,
                                    allow_redirects=False)
    except requests.Timeout:
        raise LendingUnavailable("timeout") from None
    except requests.RequestException as error:
        raise LendingUnavailable(type(error).__name__) from None
    return TransportResponse(response.status_code, dict(response.headers), response.content)


@dataclass
class LendingResponse:
    status: int
    data: dict = field(default_factory=dict)
    etag: str | None = None
    headers: dict = field(default_factory=dict)


class LendingClient:
    transport = staticmethod(requests_transport)

    def __init__(self, env, session=None, cfg=None):
        self.env = env
        self.cfg = (cfg or LendingConfig.load(env)).check()
        self.tokens = token_provider(self.cfg, session)

    @classmethod
    def for_request(cls, env):
        """A client acting as the person of the current HTTP request, if any."""
        from odoo.http import request  # noqa: PLC0415

        session = request.session if request else None
        return cls(env, session=session)

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------

    def _headers(self, *, idempotency_key=None, if_match=None, content_type=None):
        headers = {
            "Authorization": f"Bearer {self.tokens.token()}",
            "Accept": f"{JSON}, {PROBLEM}",
        }
        if content_type:
            headers["Content-Type"] = content_type
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if if_match:
            headers["If-Match"] = if_match
        if self.cfg.is_stub and self.cfg.stub_example:
            headers["X-Stub-Example"] = self.cfg.stub_example
        return headers

    def _call(self, method, template, path, *, body=None, content_type=JSON, query=None,
              idempotency_key=None, if_match=None):
        url = self.cfg.base_url + path
        if query:
            url += "?" + urlencode({k: v for k, v in query.items() if v not in (None, "")})
        payload = None
        if body is not None:
            payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        headers = self._headers(idempotency_key=idempotency_key, if_match=if_match,
                                content_type=content_type if body is not None else None)
        started = time.monotonic()
        try:
            raw = self.transport(method, url, headers, payload,
                                 (self.cfg.connect_timeout, self.cfg.read_timeout))
        except LendingUnavailable as error:
            _logger.warning("lending %s %s unavailable (%s) in %dms", method, template, error.reason,
                            (time.monotonic() - started) * 1000)
            raise
        data = self._decode(raw)
        trace = data.get("traceId") if isinstance(data, dict) else None
        _logger.info("lending %s %s -> %s in %dms%s", method, template, raw.status,
                     (time.monotonic() - started) * 1000, f" trace={trace}" if trace else "")
        if raw.status >= 500:
            raise LendingUnavailable(f"{raw.status} from the service", raw.status, trace)
        if raw.status >= 400:
            if not isinstance(data, dict) or "code" not in data:
                raise LendingUnavailable(f"{raw.status} without a problem body", raw.status)
            raise LendingRefusal(raw.status, data)
        headers = {k.lower(): v for k, v in raw.headers.items()}
        return LendingResponse(raw.status, data if isinstance(data, dict) else {}, headers.get("etag"), headers)

    @staticmethod
    def _decode(raw):
        if not raw.content:
            return {}
        try:
            return json.loads(raw.content)
        except ValueError:
            if raw.status < 400:
                raise LendingUnavailable(f"{raw.status} with a body that is not JSON", raw.status) from None
            return None

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------

    def list_clients(self, *, limit=50, cursor=None, state=None, lead_ref=None):
        return self._call("GET", "/v1/clients", "/v1/clients",
                          query={"limit": limit, "cursor": cursor, "state": state, "leadRef": lead_ref})

    def create_client(self, body, *, idempotency_key):
        return self._call("POST", "/v1/clients", "/v1/clients", body=body, idempotency_key=idempotency_key)

    def get_client(self, client_id):
        return self._call("GET", "/v1/clients/{id}", f"/v1/clients/{_id(client_id)}")

    def update_client(self, client_id, patch, *, if_match):
        return self._call("PATCH", "/v1/clients/{id}", f"/v1/clients/{_id(client_id)}", body=patch,
                          content_type=MERGE_PATCH, if_match=if_match)

    def submit_client(self, client_id, *, idempotency_key, if_match):
        return self._call("POST", "/v1/clients/{id}/submit", f"/v1/clients/{_id(client_id)}/submit",
                          idempotency_key=idempotency_key, if_match=if_match)

    def get_verifications(self, client_id):
        return self._call("GET", "/v1/clients/{id}/verifications",
                          f"/v1/clients/{_id(client_id)}/verifications")

    # ------------------------------------------------------------------
    # Phone verification
    # ------------------------------------------------------------------

    def send_phone_code(self, client_id, *, idempotency_key):
        return self._call("POST", "/v1/clients/{id}/phone-verification",
                          f"/v1/clients/{_id(client_id)}/phone-verification", idempotency_key=idempotency_key)

    def confirm_phone_code(self, client_id, code, *, idempotency_key):
        return self._call("POST", "/v1/clients/{id}/phone-verification/confirm",
                          f"/v1/clients/{_id(client_id)}/phone-verification/confirm",
                          body={"code": code}, idempotency_key=idempotency_key)

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def list_documents(self, client_id):
        return self._call("GET", "/v1/clients/{id}/documents", f"/v1/clients/{_id(client_id)}/documents")

    def request_document_upload(self, client_id, document_type, content_type, size_bytes, *, idempotency_key):
        return self._call("POST", "/v1/clients/{id}/documents", f"/v1/clients/{_id(client_id)}/documents",
                          body={"documentType": document_type, "contentType": content_type,
                                "sizeBytes": size_bytes},
                          idempotency_key=idempotency_key)

    def complete_document_upload(self, client_id, document_id, *, idempotency_key):
        return self._call("POST", "/v1/clients/{id}/documents/{documentId}/complete",
                          f"/v1/clients/{_id(client_id)}/documents/{_id(document_id)}/complete",
                          idempotency_key=idempotency_key)

    def send_upload_link(self, client_id, document_types, channel, *, idempotency_key):
        return self._call("POST", "/v1/clients/{id}/upload-links", f"/v1/clients/{_id(client_id)}/upload-links",
                          body={"documentTypes": list(document_types), "channel": channel},
                          idempotency_key=idempotency_key)

    def put_upload(self, upload_url, content, content_type):
        """Send the file to the address the service gave. Only to an allowed host,
        never with our token (the address carries its own authority)."""
        if content_type not in UPLOAD_CONTENT_TYPES:
            raise ValueError(f"content type {content_type} is not accepted")
        parsed = urlparse(upload_url)
        host = (parsed.hostname or "").lower()
        if self.cfg.is_stub and self.cfg.skip_upload_transfer:
            _logger.info("lending PUT upload skipped (stub, skip transfer)")
            return
        if parsed.scheme != "https" or host not in self.cfg.upload_hosts:
            raise LendingUnavailable(f"upload address host {host or '?'} is not allowed")
        started = time.monotonic()
        raw = self.transport("PUT", upload_url, {"Content-Type": content_type}, content,
                             (self.cfg.connect_timeout, max(self.cfg.read_timeout, 60)))
        _logger.info("lending PUT upload -> %s in %dms", raw.status, (time.monotonic() - started) * 1000)
        if raw.status >= 300:
            raise LendingUnavailable(f"upload answered {raw.status}", raw.status)


def _id(value):
    """Path ids are UUIDs: refuse anything else rather than build a strange path."""
    text = str(value or "")
    if not text or any(c not in "0123456789abcdefABCDEF-" for c in text) or len(text) > 64:
        raise ValueError("not a lending-service id")
    return text
