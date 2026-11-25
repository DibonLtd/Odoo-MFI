"""Onboarding a client through the Kapu lending service (slice 1).

The mapping from Odoo's client to the API, the checks made before anything is
sent, the push (create, contact details, documents: DECISIONS D-003, D-009),
and the commands the onboarding screen sends. Nothing here decides a client's
state: the service does, and the screen shows only the ``actions`` it returns
(D-008). Reads are never stored (D-007).

Every public function returns a result dict instead of raising, so a partly
done push keeps what it did (the client's id) and the screen can name the
field at fault: ``{"ok": True, ...}`` or ``{"ok": False, "error": {...}}``.
"""

import base64
import logging
import re

from odoo import fields
from odoo.tools import BinaryBytes

from odoo.addons.mfi_lending_api.services import LendingClient, LendingError, LendingRefusal

from ..models import rules

_logger = logging.getLogger(__name__)

# Odoo's client document kinds and the API's document types (D-014: the
# catalogue is not fixed yet; change it here only).
DOCUMENT_TYPES = {
    "national_id": "ID_DOCUMENT",
    "passport_photo": "CLIENT_PHOTO",
    "kra_certificate": "KRA_PIN_CERTIFICATE",
}
KIND_OF_TYPE = {api: kind for kind, api in DOCUMENT_TYPES.items()}
DOCUMENT_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")  # the service's catalogue names
ID_TYPES = {"national_id": "NATIONAL_ID", "alien_id": "ALIEN_ID", "passport": "PASSPORT"}
UPLOAD_CONTENT_TYPES = ("image/jpeg", "image/png", "application/pdf")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # proposed; the vault's own limit applies (vault §4)


# ----------------------------------------------------------------------
# Mapping
# ----------------------------------------------------------------------

def e164(phone):
    msisdn = rules.kenyan_msisdn(phone)
    return f"+{msisdn}" if msisdn else None


def create_body(partner):
    """CreateClient from the local record. Only what the API takes."""
    return {
        "type": "INDIVIDUAL",
        "firstName": (partner.mfi_first_name or "").strip(),
        "middleName": (partner.mfi_middle_name or "").strip() or None,
        "lastName": (partner.mfi_last_name or "").strip(),
        "idType": ID_TYPES[partner.mfi_id_type],
        "idNumber": (partner.mfi_id_number or "").strip(),
        "dateOfBirth": fields.Date.to_string(partner.mfi_date_of_birth),
        "kraPin": (partner.mfi_kra_pin or "").strip().upper() or None,
        "phone": e164(partner.phone),
        "consentToChecks": bool(partner.mfi_consent_to_checks),
    }


def contact_patch(partner):
    """The contact details the update (merge patch) carries; empty parts are left out."""
    patch = {}
    if partner.email:
        patch["email"] = partner.email.strip()
    address = {k: v for k, v in {
        "county": partner.mfi_county, "town": partner.mfi_town,
        "street": partner.mfi_street, "landmark": partner.mfi_landmark,
    }.items() if v}
    if address:
        patch["address"] = address
    kin = partner.mfi_next_of_kin_ids.filtered("is_primary")[:1] or partner.mfi_next_of_kin_ids[:1]
    if kin:
        patch["nextOfKin"] = {k: v for k, v in {
            "name": kin.full_name, "relationship": kin.relationship, "phone": e164(kin.phone) or kin.phone,
        }.items() if v}
    if partner.mfi_business_type or partner.mfi_business_location:
        business = {"type": partner.mfi_business_type} if partner.mfi_business_type else {}
        if partner.mfi_business_location:
            business["location"] = {"town": partner.mfi_business_location}
        patch["business"] = business
    return patch


def local_problems(partner):
    """What stops a push before anything is sent (TASKLIST LA-23)."""
    _ = partner.env._
    problems = []
    if not partner.is_mfi_client:
        problems.append(_("Not a microfinance client."))
    if partner.mfi_client_type == "business":
        problems.append(_("Business clients cannot be onboarded in the lending service yet."))
    if partner.mfi_blacklisted:
        problems.append(_("The client is blacklisted."))
    if not partner.mfi_consent_to_checks:
        problems.append(_("The client's consent to checks is not recorded."))
    if not (partner.mfi_first_name and partner.mfi_last_name):
        problems.append(_("First and last name are required."))
    if not partner.mfi_id_type:
        problems.append(_("The ID type is required."))
    if not partner.mfi_date_of_birth:
        problems.append(_("The date of birth is required."))
    if not e164(partner.phone):
        problems.append(_("The phone number is not a Kenyan mobile number."))
    return problems


def _document_payload(document):
    """(content, content type) of a local document, or (None, reason)."""
    if not document.file:
        return None, document.env._("No file.")
    content = bytes(document.file)
    mimetype = document.file.mimetype
    if mimetype not in UPLOAD_CONTENT_TYPES:
        return None, document.env._("%(file)s is not a JPEG, PNG or PDF.", file=document.file_name or document.kind)
    if len(content) > MAX_UPLOAD_BYTES:
        return None, document.env._("%(file)s is larger than 10 MB.", file=document.file_name or document.kind)
    return (content, mimetype), None


# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------

def failure(env, error):
    return {"ok": False, "error": error.as_dict(env)}


def local_failure(message):
    return {"ok": False, "error": {"kind": "local", "code": "local", "message": message,
                                   "field": None, "traceId": None, "status": None}}


class Onboarding:
    """One client's onboarding, as the signed-in person."""

    def __init__(self, partner):
        partner.ensure_one()
        self.partner = partner
        self.env = partner.env
        self.Command = self.env["mfi.lending.command"]
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = LendingClient.for_request(self.env)
        return self._client

    @property
    def client_id(self):
        return self.partner.sudo().mfi_lending_client_id

    def _run(self, operation, body, call, lending_ref=None):
        return self.Command._run(operation, self.partner, body, call, lending_ref=lending_ref or self.client_id)

    def _sudo_write(self, values):
        self.partner.sudo().with_context(mfi_lending_sync=True).write(values)

    # ------------------------------------------------------------------
    # The push (form button and bulk dialog)
    # ------------------------------------------------------------------

    def push(self):
        """Create the client in the lending service, send its contact details and
        the documents already held. Safe to run again: done steps are skipped."""
        partner = self.partner
        _ = self.env._
        if not rules.allowed(self.env, "lending.push"):
            return local_failure(_("You do not have permission to do this."))
        problems = local_problems(partner)
        if problems:
            rules.audit(self.env, "client.push_refused", partner, {"reasons": len(problems)})
            return local_failure(" ".join(problems))
        steps = []
        try:
            if not self.client_id:
                created = self._create()
                if not created["ok"]:
                    return created
                steps.append("created")
            current = self.client.get_client(self.client_id)
            if current.data.get("state") == "DRAFT":
                patch = contact_patch(partner)
                if patch:
                    self.client.update_client(self.client_id, patch, if_match=current.etag)
                    steps.append("contact")
                uploaded, skipped = self._upload_held_documents()
                if uploaded:
                    steps.append("documents")
            else:
                skipped = []
        except LendingError as error:
            # The client's id, if created, is kept: running the push again continues.
            self._sudo_write({"mfi_lending_sync": "in_backend" if self.client_id else "push_failed"})
            return dict(failure(self.env, error), steps=steps, clientId=self.client_id)
        self._sudo_write({"mfi_lending_sync": "in_backend"})
        return {"ok": True, "steps": steps, "clientId": self.client_id, "skipped": skipped}

    def _create(self):
        partner = self.partner
        body = create_body(partner)
        try:
            response = self._run("createClient", body,
                                 lambda key: self.client.create_client(body, idempotency_key=key))
            client_id = response.data["id"]
        except LendingRefusal as error:
            if error.code == "client_already_exists" and error.existing_client_id:
                return self._link_existing(error)
            self._sudo_write({"mfi_lending_sync": "push_failed"})
            rules.audit(self.env, "client.push_refused", partner, {"code": error.code, "trace": error.trace_id})
            return failure(self.env, error)
        except LendingError as error:
            self._sudo_write({"mfi_lending_sync": "push_failed"})
            return failure(self.env, error)
        self._sudo_write({
            "mfi_lending_client_id": client_id,
            "mfi_lending_sync": "in_backend",
            "mfi_lending_pushed_at": fields.Datetime.now(),
            "mfi_lending_pushed_by": self.env.uid,
        })
        rules.audit(self.env, "client.pushed", partner, {"lending_id": client_id})
        return {"ok": True}

    def _link_existing(self, error):
        """The service already has this person (same ID or lead): link to it, unless
        another Odoo client already holds that id."""
        other = self.env["res.partner"].sudo().search(
            [("mfi_lending_client_id", "=", error.existing_client_id), ("id", "!=", self.partner.id)], limit=1)
        if other:
            self._sudo_write({"mfi_lending_sync": "push_failed"})
            return local_failure(self.env._(
                "The lending service already has this client, linked to %(client)s in Odoo. "
                "Check for a duplicate client.", client=other.mfi_client_no or other.display_name))
        self._sudo_write({
            "mfi_lending_client_id": error.existing_client_id,
            "mfi_lending_sync": "in_backend",
            "mfi_lending_pushed_at": fields.Datetime.now(),
            "mfi_lending_pushed_by": self.env.uid,
        })
        rules.audit(self.env, "client.linked", self.partner,
                    {"lending_id": error.existing_client_id, "trace": error.trace_id})
        return {"ok": True}

    def _upload_held_documents(self):
        uploaded, skipped = 0, []
        documents = self.partner.sudo().mfi_document_ids.filtered(
            lambda d: d.kind in DOCUMENT_TYPES and not d.loan_id and d.file and not d.lending_document_id)
        for document in documents:
            payload, reason = _document_payload(document)
            if not payload:
                skipped.append(reason)
                continue
            content, content_type = payload
            self.upload(DOCUMENT_TYPES[document.kind], content, content_type, local_document=document)
            uploaded += 1
        return uploaded, skipped

    # ------------------------------------------------------------------
    # Reads for the onboarding screen: live, never stored
    # ------------------------------------------------------------------

    def read(self):
        try:
            client = self.client.get_client(self.client_id)
            documents = self.client.list_documents(self.client_id)
        except LendingError as error:
            return failure(self.env, error)
        self._documents_seen(documents.data.get("items") or [])
        result = {"ok": True, "client": client.data, "documents": documents.data}
        if client.data.get("state") not in ("DRAFT", "LAPSED"):
            result.update(self.verifications())
        return result

    def verifications(self):
        try:
            return {"ok": True, "verifications": self.client.get_verifications(self.client_id).data}
        except LendingError as error:
            return failure(self.env, error)

    def _documents_seen(self, items):
        """A local file the service now has STORED is deleted here (D-004)."""
        stored = {item["id"] for item in items if item.get("state") == "STORED"}
        if not stored:
            return
        documents = self.partner.sudo().mfi_document_ids.filtered(
            lambda d: d.lending_document_id in stored and d.file)
        for document in documents:
            document.with_context(mfi_lending_sync=True).write({
                "file": False,
                "lending_stored": True,
                "note": self.env._("Stored in the lending service"),
            })
            rules.audit(self.env, "document.purged_local_copy", self.partner,
                        {"kind": document.kind, "lending_id": document.lending_document_id})

    # ------------------------------------------------------------------
    # Commands from the onboarding screen
    # ------------------------------------------------------------------

    def _command(self, fn):
        if not rules.allowed(self.env, "lending.push"):
            return local_failure(self.env._("You do not have permission to do this."))
        try:
            return dict(fn() or {}, ok=True)
        except LendingRefusal as error:
            result = failure(self.env, error)
            if error.code == "stale_version":
                fresh = self.read()  # D-007: show what changed
                if fresh.get("ok"):
                    result["client"] = fresh["client"]
            return result
        except LendingError as error:
            return failure(self.env, error)

    def update_contact(self, values):
        """Change contact details (merge patch), then the temporary local copy (D-004)."""
        def run():
            patch, local = {}, {}
            if "phone" in values:
                phone = e164(values["phone"])
                if not phone:
                    raise LendingRefusal(400, {"code": "invalid_field", "field": "phone"})
                patch["phone"], local["phone"] = phone, values["phone"]
            if "email" in values:
                patch["email"] = values["email"] or None
                local["email"] = values["email"] or False
            if "address" in values:
                address = values["address"] or {}
                patch["address"] = {k: address.get(k) or None for k in ("county", "town", "street", "landmark")}
                local.update({f"mfi_{k}": address.get(k) or False for k in ("county", "town", "street", "landmark")})
            current = self.client.get_client(self.client_id)
            response = self.client.update_client(self.client_id, patch, if_match=current.etag)
            if local:
                self._sudo_write(local)
            rules.audit(self.env, "client.contact_updated", self.partner,
                        {"fields": ", ".join(sorted(patch)), "lending_id": self.client_id})
            return {"client": response.data}
        return self._command(run)

    def send_phone_code(self):
        def run():
            client_id = self.client_id
            response = self._run("sendPhoneCode", {"at": fields.Datetime.now().isoformat()},
                                 lambda key: self.client.send_phone_code(client_id, idempotency_key=key))
            return {"sent": response.data}
        return self._command(run)

    def confirm_phone(self, code):
        def run():
            client_id = self.client_id
            code_ = (code or "").strip()
            response = self._run("confirmPhoneCode", {"code": code_},
                                 lambda key: self.client.confirm_phone_code(client_id, code_, idempotency_key=key))
            rules.audit(self.env, "client.phone_confirmed", self.partner, {"lending_id": client_id})
            return {"confirmed": response.data}
        return self._command(run)

    def upload(self, document_type, content, content_type, local_document=None):
        """Request an upload address, send the file there, say it is sent. The file
        is never stored in Odoo on the way (it may already be, as a held document)."""
        client_id = self.client_id
        checksum = BinaryBytes(content).checksum
        body = {"documentType": document_type, "contentType": content_type, "sizeBytes": len(content)}
        requested = self._run("requestDocumentUpload", dict(body, file=checksum),
                              lambda key: self.client.request_document_upload(
                                  client_id, document_type, content_type, len(content), idempotency_key=key))
        document_id = requested.data["documentId"]
        if local_document:
            local_document.with_context(mfi_lending_sync=True).sudo().lending_document_id = document_id
        self.client.put_upload(requested.data["uploadUrl"], content, content_type)
        completed = self._run("completeDocumentUpload", {"document": document_id},
                              lambda key: self.client.complete_document_upload(
                                  client_id, document_id, idempotency_key=key))
        rules.audit(self.env, "document.sent_to_lending", self.partner,
                    {"type": document_type, "lending_id": document_id})
        return completed.data

    def upload_file(self, document_type, content, content_type):
        def run():
            _ = self.env._
            if not DOCUMENT_TYPE_RE.match(document_type or ""):
                return {"skipped": _("Unknown document type.")}
            if content_type not in UPLOAD_CONTENT_TYPES:
                return {"skipped": _("Only JPEG, PNG or PDF files are accepted.")}
            if len(content) > MAX_UPLOAD_BYTES:
                return {"skipped": _("The file is larger than 10 MB.")}
            return {"document": self.upload(document_type, content, content_type)}
        result = self._command(run)
        if result.get("skipped"):
            return local_failure(result["skipped"])
        return result

    def send_upload_link(self, document_types, channel):
        def run():
            client_id = self.client_id
            types = sorted(document_types or [])
            response = self._run("sendUploadLink", {"documentTypes": types, "channel": channel,
                                                   "at": fields.Datetime.now().isoformat()},
                                 lambda key: self.client.send_upload_link(client_id, types, channel,
                                                                          idempotency_key=key))
            return {"sent": response.data}
        return self._command(run)

    def submit(self):
        def run():
            client_id = self.client_id
            current = self.client.get_client(client_id)
            response = self._run("submitClient", {"version": current.etag},
                                 lambda key: self.client.submit_client(client_id, idempotency_key=key,
                                                                       if_match=current.etag))
            rules.audit(self.env, "client.submitted", self.partner, {"lending_id": client_id})
            return {"client": response.data}
        return self._command(run)


def decode_upload(data):
    """A file from the browser (base64), as bytes."""
    return base64.b64decode(data or b"", validate=True)
