"""Onboarding through the Kapu lending service, against the stub's own answers."""

import base64
import json
import unittest
from datetime import date
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import BinaryBytes

from odoo.addons.mfi_lending_api.services import LendingClient
from odoo.addons.mfi_lending_api.services.config import PREFIX
from odoo.addons.mfi_lending_api.services.errors import LendingUnavailable
from odoo.addons.mfi_lending_api.tests.common import STUB_URL, StubTransport

from ..services.lending import contact_patch, create_body, local_problems
from .common import MfiCase

PDF = BinaryBytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF")
PNG = BinaryBytes(base64.b64decode(  # a real 1x1 PNG
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
LENDING_ID = "0b7e5a52-6f0c-4d8e-9c1a-3f2b7d9e4a11"
STORED_ID = "5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d"  # what the stub's upload answers, STORED in its list


class LendingSetup(MfiCase):
    """Roles, the connection to the stub, and a client ready to onboard. No tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The command log writes on its own cursor: keep it inside the test's
        # transaction (HttpCase has done so already).
        if not cls._registry_patched:
            cls.enterClassContext(cls.registry_test_mode())
        params = cls.env["ir.config_parameter"].sudo()
        params.set_bool(PREFIX + "enabled", True)
        params.set_str(PREFIX + "base_url", STUB_URL)
        params.set_str(PREFIX + "auth_mode", "static")
        params.set_str(PREFIX + "upload_hosts", "vault.example.invalid")
        cls.amani = cls._ready_client()

    @classmethod
    def _ready_client(cls, id_number="23456789", **extra):
        partner = cls.env["res.partner"].create({
            "is_mfi_client": True,
            "mfi_client_type": "individual",
            "mfi_first_name": "Amani",
            "mfi_middle_name": "Wanjiru",
            "mfi_last_name": "Otieno",
            "mfi_id_type": "national_id",
            "mfi_id_number": id_number,
            "mfi_date_of_birth": date(1990, 4, 12),
            "mfi_kra_pin": "a123456789z",
            "phone": "0712 345 678",
            "email": f"{id_number}@example.com",
            "mfi_consent_to_checks": True,
            "mfi_county": "Nairobi",
            "mfi_town": "Kasarani",
            "mfi_business_type": "Mama mboga",
            "mfi_business_location": "Githurai market",
            "mfi_next_of_kin_ids": [
                (0, 0, {"full_name": "Other Kin", "relationship": "Cousin", "phone": "0700000001"}),
                (0, 0, {"full_name": "Baraka Otieno", "relationship": "Brother", "phone": "0711000002",
                        "is_primary": True}),
            ],
            "mfi_document_ids": [
                (0, 0, {"kind": "national_id", "file": PDF, "file_name": "id.pdf"}),
                (0, 0, {"kind": "passport_photo", "file": PNG, "file_name": "photo.png"}),
                (0, 0, {"kind": "mpesa_statement", "file": PDF, "file_name": "statement.pdf"}),
            ],
            **extra,
        })
        return partner

    def stub(self, **examples):
        transport = StubTransport(examples)
        patcher = patch.object(LendingClient, "transport", staticmethod(transport))
        patcher.start()
        self.addCleanup(patcher.stop)
        return transport

    def raises(self, exception):
        """Without Odoo's savepoint, whose rollback would also undo the command log in tests."""
        return unittest.TestCase.assertRaises(self, exception)


@tagged("post_install", "-at_install")
class TestLendingOnboarding(LendingSetup):

    # ------------------------------------------------------------------
    # Mapping and local checks
    # ------------------------------------------------------------------

    def test_name_is_composed(self):
        self.assertEqual(self.amani.name, "Amani Wanjiru Otieno")
        self.assertEqual(self.amani.mfi_consent_by, self.env.user)
        self.assertTrue(self.amani.mfi_consent_at)

    def test_create_body(self):
        self.assertEqual(create_body(self.amani), {
            "type": "INDIVIDUAL", "firstName": "Amani", "middleName": "Wanjiru", "lastName": "Otieno",
            "idType": "NATIONAL_ID", "idNumber": "23456789", "dateOfBirth": "1990-04-12",
            "kraPin": "A123456789Z", "phone": "+254712345678", "consentToChecks": True,
        })

    def test_contact_patch(self):
        self.assertEqual(contact_patch(self.amani), {
            "email": "23456789@example.com",
            "address": {"county": "Nairobi", "town": "Kasarani"},
            "nextOfKin": {"name": "Baraka Otieno", "relationship": "Brother", "phone": "+254711000002"},
            "business": {"type": "Mama mboga", "location": {"town": "Githurai market"}},
        })

    def test_local_problems(self):
        self.assertEqual(local_problems(self.amani), [])
        self.assertTrue(local_problems(self.client))  # an old client: no consent, names or birth date
        business = self._new_client("Hardware Ltd", "PVT-1234", "0712000000", mfi_client_type="business",
                                    mfi_contact_name="Ali")
        self.assertIn("Business clients", " ".join(local_problems(business)))

    # ------------------------------------------------------------------
    # The push
    # ------------------------------------------------------------------

    def test_push(self):
        transport = self.stub()
        result = self.amani.with_user(self.officer).mfi_lending_push()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["steps"], ["created", "contact", "documents"])
        self.assertEqual(self.amani.mfi_lending_client_id, LENDING_ID)
        self.assertEqual(self.amani.mfi_lending_sync, "in_backend")
        self.assertEqual(self.amani.mfi_lending_pushed_by, self.officer)
        calls = [(c["method"], c["url"].removeprefix(STUB_URL)) for c in transport.calls]
        self.assertEqual(calls[:3], [("POST", "/v1/clients"), ("GET", f"/v1/clients/{LENDING_ID}"),
                                     ("PATCH", f"/v1/clients/{LENDING_ID}")])
        # The ID and the photo go; the M-Pesa statement is a loan document, kept local.
        uploads = [c for c in transport.calls if c["url"].endswith("/documents")]
        self.assertEqual(sorted(json.loads(c["body"])["documentType"] for c in uploads),
                         ["CLIENT_PHOTO", "ID_DOCUMENT"])
        self.assertEqual(len([c for c in transport.calls if c["method"] == "PUT"]), 2)
        self.assertEqual(len([c for c in transport.calls if c["url"].endswith("/complete")]), 2)
        actions = self.env["mfi.audit.log"].search([("res_id", "=", self.amani.id),
                                                    ("res_model", "=", "res.partner")]).mapped("action")
        self.assertIn("client.pushed", actions)

    def test_push_again_continues_without_creating_twice(self):
        self.stub()
        self.amani.mfi_lending_push()
        transport = self.stub()
        result = self.amani.mfi_lending_push()
        self.assertTrue(result["ok"])
        self.assertNotIn(("POST", f"{STUB_URL}/v1/clients"), [(c["method"], c["url"]) for c in transport.calls])
        self.assertFalse([c for c in transport.calls if c["method"] == "PUT"])  # documents already sent

    def test_push_refused_locally_makes_no_call(self):
        transport = self.stub()
        result = self.client.mfi_lending_push()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["kind"], "local")
        self.assertIn("consent", result["error"]["message"])
        self.assertFalse(transport.calls)

    def test_push_refused_by_the_service(self):
        self.stub(createClient="invalid_field")
        result = self.amani.mfi_lending_push()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_field")
        self.assertEqual(result["error"]["field"], "phone")
        self.assertTrue(result["error"]["traceId"])
        self.assertEqual(self.amani.mfi_lending_sync, "push_failed")
        self.assertFalse(self.amani.mfi_lending_client_id)

    def test_push_when_the_service_is_down(self):
        def down(*args):
            raise LendingUnavailable("timeout")

        with patch.object(LendingClient, "transport", staticmethod(down)):
            result = self.amani.mfi_lending_push()
        self.assertEqual(result["error"]["kind"], "unavailable")
        command = self.env["mfi.lending.command"].search([("res_id", "=", self.amani.id)], limit=1)
        self.assertEqual(command.state, "unavailable")
        transport = self.stub()
        self.assertTrue(self.amani.mfi_lending_push()["ok"])
        self.assertEqual(transport.calls[0]["headers"]["Idempotency-Key"], command.idempotency_key)

    def test_already_in_the_service_is_linked(self):
        self.stub(createClient="client_already_exists")
        self.assertTrue(self.amani.mfi_lending_push()["ok"])
        self.assertEqual(self.amani.mfi_lending_client_id, LENDING_ID)
        twin = self._ready_client(id_number="34567890")
        result = twin.mfi_lending_push()
        self.assertFalse(result["ok"])
        self.assertIn(self.amani.mfi_client_no, result["error"]["message"])
        self.assertFalse(twin.mfi_lending_client_id)

    def test_bulk_push_reports_each_client(self):
        self.stub()
        business = self._new_client("Hardware Ltd", "PVT-1234", "0712000000", mfi_client_type="business",
                                    mfi_contact_name="Ali")
        results = [p.with_user(self.officer).mfi_lending_push() for p in self.amani | self.client | business]
        self.assertEqual([r["ok"] for r in results], [True, False, False])
        self.assertTrue(all(r["error"]["message"] for r in results[1:]))
        action = self.env["res.partner"].with_user(self.officer).with_context(
            active_ids=(self.amani | self.client).ids).action_mfi_lending_push_selected()
        self.assertEqual(action["tag"], "mfi_loan.lending_push")
        self.assertEqual(action["params"]["ids"], (self.amani | self.client).ids)

    def test_only_onboarding_roles_push(self):
        self.stub()
        for user in (self.finance, self.auditor, self.collections, self.ceo):
            with self.subTest(user=user.login):
                result = self.amani.with_user(user).mfi_lending_push()
                self.assertFalse(result["ok"])
                with self.assertRaises(AccessError):
                    self.amani.with_user(user).action_mfi_lending_push()
        self.assertFalse(self.amani.mfi_lending_client_id)

    def test_details_locked_after_the_push(self):
        self.stub()
        self.amani.mfi_lending_push()
        with self.assertRaisesRegex(UserError, "onboarding screen"):
            self.amani.write({"phone": "0799999999"})
        with self.assertRaisesRegex(UserError, "onboarding screen"):
            self.amani.write({"mfi_first_name": "Amina"})
        self.amani.write({"phone": self.amani.phone, "mfi_daily_income": 1500})  # unchanged, or not locked
        self.amani.write({"mfi_blacklisted": True, "mfi_blacklist_reason": "Fraud"})

    def test_no_personal_data_in_the_command_log(self):
        self.stub()
        self.amani.mfi_lending_push()
        rows = self.env["mfi.lending.command"].search([("res_id", "=", self.amani.id)])
        self.assertTrue(rows)
        text = " ".join(str(v) for row in rows.read() for v in row.values())
        for value in ("Amani", "Otieno", "23456789", "712345678", "A123456789Z", "1990"):
            self.assertNotIn(value, text)

    # ------------------------------------------------------------------
    # The onboarding screen
    # ------------------------------------------------------------------

    def _pushed(self):
        self.stub()
        self.amani.mfi_lending_push()
        return self.amani.with_user(self.officer)

    def test_read_is_live_and_purges_stored_files(self):
        client = self._pushed()
        result = client.mfi_lending_read()
        self.assertTrue(result["ok"])
        self.assertEqual(result["client"]["idNumber"], "•••••670")  # masked by the service
        self.assertIn("send_phone_code", result["client"]["actions"])
        self.assertTrue(result["partner"]["canAct"])
        stored = self.amani.mfi_document_ids.filtered("lending_stored")
        self.assertTrue(stored)
        self.assertFalse(any(d.file for d in stored))
        self.assertTrue(self.amani.mfi_documents_complete)  # still counts for local loans
        statement = self.amani.mfi_document_ids.filtered(lambda d: d.kind == "mpesa_statement")
        self.assertTrue(statement.file)

    def test_read_shows_held_without_reasons(self):
        client = self._pushed()
        self.stub(getClient="held", getVerifications="held")
        result = client.mfi_lending_read()
        self.assertEqual(result["client"]["state"], "HELD")
        self.assertEqual(result["verifications"]["checks"], [])
        self.assertEqual(result["verifications"]["nextStep"], "NONE")

    def test_read_needs_a_microfinance_role(self):
        self._pushed()
        stranger = self.env["res.users"].create({"name": "Stranger", "login": "stranger",
                                                  "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        with self.assertRaises(AccessError):
            self.amani.with_user(stranger).mfi_lending_read()

    def test_phone(self):
        client = self._pushed()
        self.assertTrue(client.mfi_lending_command("send_phone_code")["sent"]["sentTo"])
        self.stub(confirmPhoneCode="code_incorrect")
        result = client.mfi_lending_command("confirm_phone", {"code": "000000"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["field"], "code")
        self.stub()
        self.assertTrue(client.mfi_lending_command("confirm_phone", {"code": "123456"})["confirmed"]["phoneConfirmed"])
        self.stub(sendPhoneCode="too_many_requests")
        self.assertEqual(client.mfi_lending_command("send_phone_code")["error"]["retryAfterSeconds"], 60)

    def test_update_contact_changes_the_local_copy(self):
        client = self._pushed()
        transport = self.stub()
        result = client.mfi_lending_command("update_contact", {"values": {"phone": "0722 111 222",
                                                                          "address": {"county": "Kiambu"}}})
        self.assertTrue(result["ok"], result)
        patch_call = [c for c in transport.calls if c["method"] == "PATCH"][0]
        body = json.loads(patch_call["body"])
        self.assertEqual(body["phone"], "+254722111222")
        self.assertEqual(body["address"], {"county": "Kiambu", "town": None, "street": None, "landmark": None})
        self.assertEqual(patch_call["headers"]["If-Match"], '"1"')
        self.assertEqual(self.amani.phone, "0722 111 222")
        self.assertEqual(self.amani.mfi_county, "Kiambu")

    def test_update_contact_stale_version_rereads(self):
        client = self._pushed()
        self.stub(updateClient="stale_version")
        result = client.mfi_lending_command("update_contact", {"values": {"email": "new@example.com"}})
        self.assertEqual(result["error"]["code"], "stale_version")
        self.assertEqual(result["client"]["id"], LENDING_ID)
        self.assertNotEqual(self.amani.email, "new@example.com")

    def test_upload_from_the_screen_is_not_stored(self):
        client = self._pushed()
        documents = self.amani.mfi_document_ids
        transport = self.stub()
        result = client.mfi_lending_command("upload_file", {
            "documentType": "KRA_PIN_CERTIFICATE", "contentType": "application/pdf",
            "data": base64.b64encode(bytes(PDF)).decode()})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["document"]["state"], "RECEIVED")
        self.assertEqual(self.amani.mfi_document_ids, documents)
        self.assertEqual([c["method"] for c in transport.calls], ["POST", "PUT", "POST"])
        refused = client.mfi_lending_command("upload_file", {
            "documentType": "KRA_PIN_CERTIFICATE", "contentType": "text/html", "data": "PGgxPg=="})
        self.assertEqual(refused["error"]["kind"], "local")

    def test_submit(self):
        client = self._pushed()
        self.stub(submitClient="documents_missing")
        result = client.mfi_lending_command("submit")
        self.assertEqual(result["error"]["missingDocuments"], ["CLIENT_PHOTO"])
        self.stub()
        result = client.mfi_lending_command("submit")
        self.assertEqual(result["client"]["state"], "VERIFYING")
        self.stub(getVerifications="correction")
        verifications = client.mfi_lending_command("verifications")["verifications"]
        self.assertEqual(verifications["nextStep"], "CORRECT_FIELD")

    def test_screen_commands_need_an_onboarding_role(self):
        client = self._pushed()
        result = self.amani.with_user(self.auditor).mfi_lending_command("send_phone_code")
        self.assertFalse(result["ok"])
        with self.assertRaises(UserError):
            client.mfi_lending_command("delete_everything")

    def test_live_list_links_odoo_clients(self):
        self._pushed()
        result = self.env["res.partner"].with_user(self.officer).mfi_lending_list(state="DRAFT")
        items = result["page"]["items"]
        self.assertEqual(items[0]["odoo"]["id"], self.amani.id)
        self.assertIsNone(items[1]["odoo"])
