"""What the lending service answers when it does not do what was asked.

Two kinds, kept apart because Odoo reacts to them differently:

* ``LendingRefusal``: the service answered and said no, with a reason (an
  RFC 9457 problem). Branch on ``code``; never on ``detail``, which is for
  developers. Show ``message(env)`` to the person, highlight ``field``.
* ``LendingUnavailable``: no usable answer (network, timeout, 5xx, a body that
  is not a problem). The same command may be retried with the same key.

Neither carries personal data: ``detail`` from the service holds none, and we
add none (DECISIONS D-012).
"""

from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

# The API's RefusalCode values (kapu-lending.v1.yaml), with what to tell staff.
REFUSAL_MESSAGES = {
    "unauthenticated": _lt("The lending service did not accept your sign-in. Sign in again; if it persists, ask an administrator to check the connection."),
    "not_permitted": _lt("Your role in the lending service does not allow this."),
    "not_found": _lt("The lending service has no such record."),
    "invalid_field": _lt("The lending service refused a field as invalid."),
    "missing_field": _lt("The lending service needs a field that is missing."),
    "idempotency_key_required": _lt("The request was sent without its safety key. This is a fault in Odoo: report it with the reference."),
    "invalid_cursor": _lt("The list moved on. Start again from the first page."),
    "consent_required": _lt("The client's consent to checks is required."),
    "kra_pin_missing": _lt("A KRA PIN certificate needs the client's KRA PIN keyed in first."),
    "idempotency_key_reused": _lt("This action was already sent with different details. Start it again."),
    "client_already_exists": _lt("The lending service already has a client with this ID number or from this lead."),
    "wrong_state": _lt("The client's state in the lending service does not allow this now. Refresh to see what can be done."),
    "phone_not_confirmed": _lt("Confirm the client's phone before submitting."),
    "documents_missing": _lt("Required documents are not yet stored."),
    "request_in_progress": _lt("The same request is still being processed. Try again in a moment."),
    "code_incorrect": _lt("The code is incorrect. Ask the client to read it again."),
    "code_expired": _lt("The code has expired. Send a new one."),
    "stale_version": _lt("Someone changed this client since you opened it. It has been refreshed: check the changes and try again."),
    "if_match_required": _lt("The request was sent without its version. This is a fault in Odoo: report it with the reference."),
    "too_many_requests": _lt("Too many codes have been sent. Wait before sending another."),
    "not_implemented": _lt("The lending service does not offer this yet."),
}
UNKNOWN_REFUSAL = _lt("The lending service refused the request.")
UNAVAILABLE = _lt("The lending service could not be reached. Nothing was lost: try again shortly.")
REFERENCE = _lt("Reference: %s")

# The request fields the service may name, in staff's words.
FIELD_LABELS = {
    "firstName": _lt("First name"),
    "middleName": _lt("Middle name"),
    "lastName": _lt("Last name"),
    "idType": _lt("ID type"),
    "idNumber": _lt("ID number"),
    "dateOfBirth": _lt("Date of birth"),
    "kraPin": _lt("KRA PIN"),
    "phone": _lt("Phone"),
    "email": _lt("Email"),
    "consentToChecks": _lt("Consent to checks"),
    "code": _lt("Code"),
    "address": _lt("Address"),
    "nextOfKin": _lt("Next of kin"),
    "business": _lt("Business"),
    "documentType": _lt("Document type"),
    "contentType": _lt("File type"),
    "cursor": _lt("Page"),
}


def field_label(env, field):
    label = FIELD_LABELS.get(field)
    return env._(label) if label else field


class LendingError(Exception):
    """Base for every answer that is not what was asked for."""

    def message(self, env):
        raise NotImplementedError


class LendingRefusal(LendingError):
    """The service said no, with a reason."""

    def __init__(self, status, problem):
        problem = problem or {}
        self.status = status
        self.code = problem.get("code") or "unknown"
        self.field = problem.get("field")
        self.trace_id = problem.get("traceId")
        self.detail = problem.get("detail")  # for developers and logs; never shown as the reason
        self.existing_client_id = problem.get("existingClientId")
        self.missing_documents = problem.get("missingDocuments") or []
        self.retry_after_seconds = problem.get("retryAfterSeconds")
        super().__init__(f"{status} {self.code}")

    def message(self, env):
        text = env._(REFUSAL_MESSAGES.get(self.code, UNKNOWN_REFUSAL))
        if self.field:
            text = f"{text} ({field_label(env, self.field)})"
        if self.missing_documents:
            text = f"{text}: {', '.join(self.missing_documents)}"
        if self.trace_id:
            text = f"{text} {env._(REFERENCE) % self.trace_id}"
        return text

    def as_dict(self, env):
        return {
            "kind": "refusal",
            "status": self.status,
            "code": self.code,
            "field": self.field,
            "traceId": self.trace_id,
            "message": self.message(env),
            "existingClientId": self.existing_client_id,
            "missingDocuments": self.missing_documents,
            "retryAfterSeconds": self.retry_after_seconds,
        }


class LendingUnavailable(LendingError):
    """No usable answer: try again later, with the same key."""

    def __init__(self, reason, status=None, trace_id=None):
        self.reason = reason  # technical, for logs only
        self.status = status
        self.trace_id = trace_id
        self.code = "unavailable"
        super().__init__(reason)

    def message(self, env):
        text = env._(UNAVAILABLE)
        if self.trace_id:
            text = f"{text} {env._(REFERENCE) % self.trace_id}"
        return text

    def as_dict(self, env):
        return {"kind": "unavailable", "status": self.status, "code": self.code,
                "traceId": self.trace_id, "message": self.message(env)}


class LendingNotConfigured(LendingError):
    """The connection is switched off or incomplete: a set-up problem, not the service's."""

    def __init__(self, what):
        self.what = what
        self.code = "not_configured"
        self.status = None
        self.trace_id = None
        super().__init__(what)

    def message(self, env):
        return env._("The lending service connection is not set up: %s. Ask an administrator (Settings, Kapu lending).") % self.what

    def as_dict(self, env):
        return {"kind": "not_configured", "status": None, "code": self.code,
                "traceId": None, "message": self.message(env)}
