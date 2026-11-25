"""Against the real WireMock stub (TASKLIST LA-17), over the network.

Skipped unless KAPU_LENDING_STUB_URL is set, e.g.:

    docker run --rm -p 8094:8080 -v "$PWD/Requirements:/home/wiremock/mappings" wiremock/wiremock:3.13.1
    KAPU_LENDING_STUB_URL=http://localhost:8094 odoo ... --test-tags /mfi_lending_api:TestStubLive
"""

import os
import unittest
import uuid

from odoo.tests import TransactionCase, tagged

from ..services.client import LendingClient
from ..services.config import PREFIX
from ..services.errors import LendingRefusal

STUB = os.environ.get("KAPU_LENDING_STUB_URL")


@tagged("post_install", "-at_install", "lending_stub")
@unittest.skipUnless(STUB, "KAPU_LENDING_STUB_URL is not set")
class TestStubLive(TransactionCase):

    def setUp(self):
        super().setUp()
        params = self.env["ir.config_parameter"].sudo()
        params.set_bool(PREFIX + "enabled", True)
        params.set_str(PREFIX + "base_url", STUB)
        params.set_str(PREFIX + "auth_mode", "static")
        params.set_str(PREFIX + "stub_example", "")
        self.client = LendingClient(self.env)

    def test_onboarding_calls(self):
        created = self.client.create_client({
            "type": "INDIVIDUAL", "firstName": "Amani", "lastName": "Otieno", "idType": "NATIONAL_ID",
            "idNumber": "12345670", "dateOfBirth": "1990-04-12", "phone": "+254712345678", "consentToChecks": True,
        }, idempotency_key=str(uuid.uuid4()))
        self.assertEqual(created.status, 201)
        client_id = created.data["id"]
        read = self.client.get_client(client_id)
        self.assertTrue(read.etag)
        self.assertEqual(self.client.update_client(client_id, {"email": None}, if_match=read.etag).status, 200)
        self.assertEqual(self.client.send_phone_code(client_id, idempotency_key=str(uuid.uuid4())).status, 202)
        self.assertEqual(self.client.list_documents(client_id).status, 200)
        self.assertEqual(self.client.submit_client(client_id, idempotency_key=str(uuid.uuid4()),
                                                   if_match=read.etag).data["state"], "VERIFYING")
        self.assertIn(self.client.get_verifications(client_id).data["nextStep"], ("WAIT", "CORRECT_FIELD", "NONE"))

    def test_named_example_and_refusal(self):
        self.env["ir.config_parameter"].sudo().set_str(PREFIX + "stub_example", "phone_not_confirmed")
        client = LendingClient(self.env)
        with self.assertRaises(LendingRefusal) as caught:
            client.submit_client("0b7e5a52-6f0c-4d8e-9c1a-3f2b7d9e4a11", idempotency_key=str(uuid.uuid4()),
                                 if_match='"1"')
        self.assertEqual(caught.exception.code, "phone_not_confirmed")
