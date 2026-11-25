import unittest
from unittest.mock import patch

from odoo.tests import tagged

from ..models.lending_command import MfiLendingCommand
from ..services.client import LendingClient
from ..services.errors import LendingRefusal, LendingUnavailable
from .common import LendingCase

BODY = {"type": "INDIVIDUAL", "firstName": "Amani", "lastName": "Otieno", "idNumber": "12345670",
        "phone": "+254712345678", "consentToChecks": True}


@tagged("post_install", "-at_install")
class TestLendingCommands(LendingCase):

    def setUp(self):
        super().setUp()
        self.Command = self.env["mfi.lending.command"]
        self.partner = self.env["res.partner"].create({"name": "Command subject"})

    def raises(self, exception):
        """Without Odoo's savepoint: in tests the log's own cursor shares this
        transaction, and that savepoint's rollback would erase the row."""
        return unittest.TestCase.assertRaises(self, exception)

    def _create(self, body=BODY):
        client = self.client()
        return self.Command._run("createClient", self.partner, body,
                                 lambda key: client.create_client(body, idempotency_key=key))

    def _rows(self):
        return self.Command.search([("res_model", "=", "res.partner"), ("res_id", "=", self.partner.id)],
                                   order="id")

    def test_accepted_is_recorded_with_the_new_id(self):
        transport = self.stub()
        self._create()
        row = self._rows()
        self.assertEqual(len(row), 1)
        self.assertEqual(row.state, "accepted")
        self.assertEqual(row.http_status, 201)
        self.assertEqual(row.lending_ref, "0b7e5a52-6f0c-4d8e-9c1a-3f2b7d9e4a11")
        self.assertEqual(row.user_id, self.env.user)
        self.assertEqual(transport.calls[0]["headers"]["Idempotency-Key"], row.idempotency_key)

    def test_retry_after_an_outage_reuses_the_key(self):
        def down(*args):
            raise LendingUnavailable("timeout")

        with patch.object(LendingClient, "transport", staticmethod(down)), self.raises(LendingUnavailable):
            self._create()
        first = self._rows()
        self.assertEqual(first.state, "unavailable")
        transport = self.stub()
        self._create()
        self.assertEqual(self._rows(), first)  # the same row, finished
        self.assertEqual(first.state, "accepted")
        self.assertEqual(first.attempts, 2)
        self.assertEqual(transport.calls[0]["headers"]["Idempotency-Key"], first.idempotency_key)

    def test_a_new_action_gets_a_new_key(self):
        self.stub()
        self._create()
        self._create()  # done once already: doing it again is a new action
        self._create(dict(BODY, firstName="Amina"))  # different details: a new action
        keys = self._rows().mapped("idempotency_key")
        self.assertEqual(len(set(keys)), 3)

    def test_refusal_is_recorded_and_raised(self):
        self.stub(createClient="consent_required")
        with self.raises(LendingRefusal):
            self._create()
        row = self._rows()
        self.assertEqual((row.state, row.code, row.http_status), ("refused", "consent_required", 422))
        self.assertTrue(row.trace_id)

    def test_request_in_progress_is_retried_with_the_same_key(self):
        answers = iter(["request_in_progress", "request_in_progress", None])
        transport = self.stub()

        def flaky(method, url, headers, body, timeout):
            example = next(answers)
            if example:
                headers = dict(headers, **{"X-Stub-Example": example})
            return transport(method, url, headers, body, timeout)

        with patch.object(LendingClient, "transport", staticmethod(flaky)), \
                patch.object(MfiLendingCommand, "_sleep") as sleep:
            self._create()
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(len({c["headers"]["Idempotency-Key"] for c in transport.calls}), 1)
        self.assertEqual(self._rows().state, "accepted")

    def test_no_personal_data_in_the_log(self):
        self.stub()
        self._create()
        row = self._rows().read()[0]
        text = " ".join(str(v) for v in row.values())
        for value in ("Amani", "Otieno", "12345670", "254712345678"):
            self.assertNotIn(value, text)

    def test_purge_after_thirteen_months(self):
        self.stub()
        self._create()
        row = self._rows()
        self.env.cr.execute("UPDATE mfi_lending_command SET create_date = now() - interval '400 days' WHERE id = %s",
                            [row.id])
        self.Command.invalidate_model()
        self.Command._cron_purge()
        self.assertFalse(row.exists())
