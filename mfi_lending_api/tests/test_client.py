import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from ..services import auth
from ..services.client import LendingClient, TransportResponse
from ..services.config import PREFIX, LendingConfig
from ..services.errors import (
    REFUSAL_MESSAGES,
    LendingNotConfigured,
    LendingRefusal,
    LendingUnavailable,
)
from .common import MAPPINGS, LendingCase, operation_of

CLIENT_ID = "0b7e5a52-6f0c-4d8e-9c1a-3f2b7d9e4a11"
DOC_ID = "5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d"
KEY = "6f1c2d3e-4a5b-4c6d-8e7f-9a0b1c2d3e4f"
CREATE = {"type": "INDIVIDUAL", "firstName": "Amani", "lastName": "Otieno", "idType": "NATIONAL_ID",
          "idNumber": "12345670", "dateOfBirth": "1990-04-12", "phone": "+254712345678",
          "consentToChecks": True}

# Each operation of the API, called the way Odoo calls it.
OPERATIONS = {
    "listClients": lambda c: c.list_clients(limit=10),
    "createClient": lambda c: c.create_client(CREATE, idempotency_key=KEY),
    "getClient": lambda c: c.get_client(CLIENT_ID),
    "updateClient": lambda c: c.update_client(CLIENT_ID, {"email": "a@example.com"}, if_match='"1"'),
    "sendPhoneCode": lambda c: c.send_phone_code(CLIENT_ID, idempotency_key=KEY),
    "confirmPhoneCode": lambda c: c.confirm_phone_code(CLIENT_ID, "123456", idempotency_key=KEY),
    "listDocuments": lambda c: c.list_documents(CLIENT_ID),
    "requestDocumentUpload": lambda c: c.request_document_upload(CLIENT_ID, "ID_DOCUMENT", "image/jpeg", 1000,
                                                                 idempotency_key=KEY),
    "completeDocumentUpload": lambda c: c.complete_document_upload(CLIENT_ID, DOC_ID, idempotency_key=KEY),
    "sendUploadLink": lambda c: c.send_upload_link(CLIENT_ID, ["CLIENT_PHOTO"], "SMS", idempotency_key=KEY),
    "submitClient": lambda c: c.submit_client(CLIENT_ID, idempotency_key=KEY, if_match='"1"'),
    "getVerifications": lambda c: c.get_verifications(CLIENT_ID),
    "revealClientFields": None,  # not built in slice 1 (TASKLIST LA-68)
}


@tagged("post_install", "-at_install")
class TestLendingClient(LendingCase):

    def test_every_operation_answers_its_default(self):
        self.stub()
        client = self.client()
        expected = {
            "listClients": 200, "createClient": 201, "getClient": 200, "updateClient": 200,
            "sendPhoneCode": 202, "confirmPhoneCode": 200, "listDocuments": 200,
            "requestDocumentUpload": 201, "completeDocumentUpload": 200, "sendUploadLink": 202,
            "submitClient": 202, "getVerifications": 200,
        }
        for operation, status in expected.items():
            with self.subTest(operation=operation):
                self.assertEqual(OPERATIONS[operation](client).status, status)

    def test_create_returns_id_and_version(self):
        self.stub()
        response = self.client().create_client(CREATE, idempotency_key=KEY)
        self.assertEqual(response.data["id"], CLIENT_ID)
        self.assertEqual(response.data["state"], "DRAFT")
        self.assertEqual(response.etag, '"1"')

    def test_headers(self):
        transport = self.stub()
        client = self.client()
        client.create_client(CREATE, idempotency_key=KEY)
        client.update_client(CLIENT_ID, {"email": None}, if_match='"3"')
        client.get_client(CLIENT_ID)
        post, patch_, get = transport.calls
        self.assertEqual(post["headers"]["Idempotency-Key"], KEY)
        self.assertEqual(post["headers"]["Content-Type"], "application/json")
        self.assertTrue(post["headers"]["Authorization"].startswith("Bearer "))
        self.assertEqual(json.loads(post["body"])["consentToChecks"], True)
        self.assertEqual(patch_["headers"]["If-Match"], '"3"')
        self.assertEqual(patch_["headers"]["Content-Type"], "application/merge-patch+json")
        self.assertEqual(json.loads(patch_["body"]), {"email": None})  # null clears, as merge patch says
        self.assertNotIn("Idempotency-Key", patch_["headers"])
        self.assertNotIn("Idempotency-Key", get["headers"])
        self.assertNotIn("X-Stub-Example", get["headers"])

    def test_stub_example_header_only_in_static_mode(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_str(PREFIX + "stub_example", "held")
        transport = self.stub()
        self.assertEqual(self.client().get_client(CLIENT_ID).data["state"], "HELD")
        self.assertEqual(transport.calls[0]["headers"]["X-Stub-Example"], "held")

    def test_every_refusal_in_the_contract_is_mapped(self):
        """Each named problem answer in the stub becomes a LendingRefusal with text for staff."""
        seen = set()
        for mapping in MAPPINGS:
            response = mapping["response"]
            example = (mapping["request"].get("headers") or {}).get("X-Stub-Example", {}).get("equalTo")
            call = OPERATIONS[operation_of(mapping)]
            if not example or response["status"] < 400 or call is None:
                continue
            with self.subTest(mapping=mapping["name"]):
                self.stub(**{operation_of(mapping): example})
                with self.assertRaises(LendingRefusal) as caught:
                    call(self.client())
                error = caught.exception
                self.assertEqual(error.code, response["jsonBody"]["code"])
                self.assertEqual(error.status, response["status"])
                self.assertIn(error.code, REFUSAL_MESSAGES)
                self.assertTrue(error.message(self.env))
                self.assertIn(error.trace_id, error.message(self.env))
                seen.add(error.code)
        self.assertEqual(seen, set(REFUSAL_MESSAGES) - {"not_implemented"})

    def test_refusal_extras(self):
        self.stub(createClient="client_already_exists", submitClient="documents_missing",
                  sendPhoneCode="too_many_requests")
        client = self.client()
        with self.assertRaises(LendingRefusal) as caught:
            client.create_client(CREATE, idempotency_key=KEY)
        self.assertEqual(caught.exception.existing_client_id, CLIENT_ID)
        self.assertEqual(caught.exception.field, "idNumber")
        with self.assertRaises(LendingRefusal) as caught:
            client.submit_client(CLIENT_ID, idempotency_key=KEY, if_match='"1"')
        self.assertEqual(caught.exception.missing_documents, ["CLIENT_PHOTO"])
        self.assertIn("CLIENT_PHOTO", caught.exception.message(self.env))
        with self.assertRaises(LendingRefusal) as caught:
            client.send_phone_code(CLIENT_ID, idempotency_key=KEY)
        self.assertEqual(caught.exception.retry_after_seconds, 60)

    def test_swahili(self):
        self.stub(confirmPhoneCode="code_expired")
        with self.assertRaises(LendingRefusal) as caught:
            self.client().confirm_phone_code(CLIENT_ID, "123456", idempotency_key=KEY)
        self.env["res.lang"]._activate_lang("sw")
        self.env["ir.module.module"].search([("name", "=", "mfi_lending_api")])._update_translations(["sw"])
        text = caught.exception.message(self.env(context={"lang": "sw"}))
        self.assertIn("Msimbo", text)

    def test_missing_keys_count_as_null(self):
        self.stub()
        client = self.client().get_client(CLIENT_ID).data
        self.assertIsNone(client.get("email"))  # the stub drops null keys

    def test_outages(self):
        def failing(status, body):
            return staticmethod(lambda *args: TransportResponse(status, {}, body))

        for status, body in ((503, b"<html>down</html>"), (500, b"{}"), (404, b"not json"), (200, b"not json")):
            with self.subTest(status=status), patch.object(LendingClient, "transport", failing(status, body)):
                with self.assertRaises(LendingUnavailable):
                    self.client().get_client(CLIENT_ID)

        def timeout(*args):
            raise LendingUnavailable("timeout")

        with patch.object(LendingClient, "transport", staticmethod(timeout)), self.assertRaises(LendingUnavailable):
            self.client().get_client(CLIENT_ID)

    def test_ids_are_checked_before_building_a_path(self):
        self.stub()
        with self.assertRaises(ValueError):
            self.client().get_client("../admin")

    def test_upload_goes_only_to_allowed_hosts(self):
        transport = self.stub()
        client = self.client()
        client.put_upload("https://vault.example.invalid/uploads/x?token=t", b"%PDF", "application/pdf")
        put = transport.calls[-1]
        self.assertEqual(put["method"], "PUT")
        self.assertNotIn("Authorization", put["headers"])  # our token never goes to the upload address
        for url in ("https://evil.example/uploads/x", "http://vault.example.invalid/x"):
            with self.subTest(url=url), self.assertRaises(LendingUnavailable):
                client.put_upload(url, b"%PDF", "application/pdf")
        with self.assertRaises(ValueError):
            client.put_upload("https://vault.example.invalid/x", b"MZ", "application/x-msdownload")

    def test_upload_transfer_skipped_on_the_stub_only_when_asked(self):
        self.env["ir.config_parameter"].sudo().set_bool(PREFIX + "skip_upload_transfer", True)
        transport = self.stub()
        self.client().put_upload("https://anything.invalid/x", b"%PDF", "application/pdf")
        self.assertFalse(transport.calls)


@tagged("post_install", "-at_install")
class TestLendingConfig(LendingCase):

    def _cfg(self, **values):
        params = self.env["ir.config_parameter"].sudo()
        for key, value in values.items():
            (params.set_bool if isinstance(value, bool) else params.set_str)(PREFIX + key, value)
        return LendingConfig.load(self.env)

    def test_checks(self):
        self.assertTrue(self._cfg().check())
        for values, words in (
            ({"enabled": False}, "switched off"),
            ({"base_url": "ftp://x"}, "web address"),
            ({"auth_mode": "service_account", "base_url": "http://x.test"}, "https"),
            ({"auth_mode": "service_account", "base_url": "https://x.test", "token_url": ""}, "Keycloak"),
        ):
            with self.subTest(values=values), self.assertRaisesRegex(LendingNotConfigured, words):
                self._cfg(**values).check()
            self._cfg(enabled=True, base_url="http://stub.test", auth_mode="static")

    def test_secrets_never_in_the_database(self):
        settings = self.env["res.config.settings"].create({
            "mfi_lending_enabled": True, "mfi_lending_base_url": "https://lending.test",
            "mfi_lending_auth_mode": "service_account", "mfi_lending_client_id": "odoo",
            "mfi_lending_token_url": "https://kc.test/realms/staff/protocol/openid-connect/token",
        })
        settings.execute()
        self.assertFalse(any("secret" in name or name.endswith("token") for name in settings._fields
                             if name.startswith("mfi_lending")))
        keys = self.env["ir.config_parameter"].sudo().search([("key", "like", PREFIX)]).mapped("key")
        self.assertFalse([k for k in keys if "secret" in k or k.endswith("static_token")])

    def test_service_account_token_cached_in_memory(self):
        cfg = self._cfg(auth_mode="service_account", base_url="https://lending.test",
                        token_url="https://kc.test/token", client_id="odoo")
        auth.clear_cached_tokens()
        answer = type("R", (), {"status_code": 200, "json": lambda self: {"access_token": "t1", "expires_in": 300}})()
        with patch.object(auth, "secret", return_value="s3cret"), \
                patch.object(auth.requests, "post", return_value=answer) as post:
            provider = auth.token_provider(cfg)
            self.assertEqual(provider.token(), "t1")
            self.assertEqual(provider.token(), "t1")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "client_credentials")
        auth.clear_cached_tokens()

    def test_token_exchange_needs_a_person(self):
        cfg = self._cfg(auth_mode="token_exchange", base_url="https://lending.test",
                        token_url="https://kc.test/token", client_id="odoo")
        with self.assertRaises(LendingNotConfigured):
            auth.token_provider(cfg, None).token()  # a background job has no person
        with self.assertRaises(LendingRefusal):
            auth.token_provider(cfg, {}).token()  # signed in without Keycloak
        session = {auth.SUBJECT_TOKEN_KEY: "person-token", auth.SUBJECT_EXPIRES_KEY: __import__("time").time() + 300}
        answer = type("R", (), {"status_code": 200, "json": lambda self: {"access_token": "x1", "expires_in": 300}})()
        with patch.object(auth, "secret", return_value="s3cret"), \
                patch.object(auth.requests, "post", return_value=answer) as post:
            self.assertEqual(auth.token_provider(cfg, session).token(), "x1")
            self.assertEqual(auth.token_provider(cfg, session).token(), "x1")  # from the session
        data = post.call_args.kwargs["data"]
        self.assertEqual(data["grant_type"], "urn:ietf:params:oauth:grant-type:token-exchange")
        self.assertEqual(data["subject_token"], "person-token")
        self.assertEqual(data["audience"], "lending-service")
        self.assertEqual(post.call_count, 1)

    def test_test_connection_button(self):
        self.stub()
        settings = self.env["res.config.settings"].create({
            "mfi_lending_enabled": True, "mfi_lending_base_url": "http://stub.test", "mfi_lending_auth_mode": "static"})
        self.assertEqual(settings.action_mfi_lending_test()["params"]["type"], "success")
        self.stub(listClients="unauthenticated")
        with self.assertRaisesRegex(UserError, "sign-in"):
            settings.action_mfi_lending_test()

    def test_token_exchange_renews_the_person_token(self):
        """Keycloak access tokens last minutes: the refresh token renews it, in the session only."""
        import time  # noqa: PLC0415

        cfg = self._cfg(auth_mode="token_exchange", base_url="https://lending.test",
                        token_url="https://kc.test/token", client_id="odoo")
        session = {auth.SUBJECT_TOKEN_KEY: "old", auth.SUBJECT_REFRESH_KEY: "refresh-1",
                   auth.SUBJECT_EXPIRES_KEY: time.time() - 10}
        answers = iter([
            {"access_token": "fresh", "refresh_token": "refresh-2", "expires_in": 300},  # refresh
            {"access_token": "exchanged", "expires_in": 300},  # exchange
        ])

        def answer(*args, **kwargs):
            return type("R", (), {"status_code": 200, "json": lambda self, a=next(answers): a})()

        with patch.object(auth, "secret", return_value="s3cret"), \
                patch.object(auth.requests, "post", side_effect=answer) as post:
            self.assertEqual(auth.token_provider(cfg, session).token(), "exchanged")
        refresh_call, exchange_call = post.call_args_list
        self.assertEqual(refresh_call.kwargs["data"]["grant_type"], "refresh_token")
        self.assertEqual(refresh_call.kwargs["data"]["refresh_token"], "refresh-1")
        self.assertEqual(exchange_call.kwargs["data"]["subject_token"], "fresh")
        self.assertEqual(session[auth.SUBJECT_REFRESH_KEY], "refresh-2")
        # Keycloak session over: refused, and the person signs in again
        session = {auth.SUBJECT_TOKEN_KEY: "old", auth.SUBJECT_REFRESH_KEY: "dead",
                   auth.SUBJECT_EXPIRES_KEY: time.time() - 10}
        denied = type("R", (), {"status_code": 400, "json": lambda self: {"error": "invalid_grant"}})()
        with patch.object(auth, "secret", return_value="s3cret"), \
                patch.object(auth.requests, "post", return_value=denied), self.assertRaises(LendingRefusal):
            auth.token_provider(cfg, session).token()
        self.assertNotIn(auth.SUBJECT_TOKEN_KEY, session)
