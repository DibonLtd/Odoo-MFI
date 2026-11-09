from datetime import timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import MfiCase


@tagged("post_install", "-at_install")
class TestBackOffice(MfiCase):
    """Client onboarding, collections, the dashboard, reports and settings."""

    # ------------------------------------------------------------------
    # Client onboarding
    # ------------------------------------------------------------------

    def test_client_number(self):
        self.assertTrue(self.client.mfi_client_no.startswith("RC-C-"))

    def test_client_rules(self):
        cases = [
            ({"mfi_id_number": "12"}, "valid ID"),
            ({"email": "not-an-email"}, "email"),
            ({"mfi_kra_pin": "123"}, "KRA PIN"),
            ({"phone": False}, "phone"),
            ({"mfi_id_number": "12345678"}, "already exists"),  # the test client's ID
        ]
        for extra, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValidationError, message):
                self._new_client("Another Client", "99999999", "0711111111", **extra)

    def test_business_needs_contact_person(self):
        with self.assertRaisesRegex(ValidationError, "contact person"):
            self._new_client("Mohamed Hardware Ltd", "PVT-123ABC", "0711111111", mfi_client_type="business")
        business = self._new_client("Mohamed Hardware Ltd", "PVT-123ABC", "0711111111",
                                    mfi_client_type="business", mfi_contact_name="Ali Mohamed")
        self.assertIn("Business registration certificate", business.mfi_documents_missing)

    def test_only_originators_onboard(self):
        Partner = self.env["res.partner"]
        with self.assertRaises(AccessError):
            Partner.with_user(self.finance).create({"name": "Someone", "is_mfi_client": True})

    def test_masked_phone(self):
        self.assertEqual(self.client.mfi_phone_masked, "•••• ••• 678")

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def test_contact_log_and_promises(self):
        loan = self._active(self._new_loan(), days_ago=5)
        Note = self.env["mfi.collection.note"]
        with self.assertRaises(AccessError):
            Note.with_user(self.finance).create({"loan_id": loan.id, "kind": "call", "note": "x"})
        with self.assertRaisesRegex(UserError, "Promise date"):
            Note.with_user(self.collections).create({"loan_id": loan.id, "kind": "promise"})
        Note.with_user(self.collections).create({"loan_id": loan.id, "kind": "call", "note": "No answer"})
        promise = Note.with_user(self.collections).create({
            "loan_id": loan.id, "kind": "promise", "note": "Will pay Friday",
            "promise_date": self.today + timedelta(days=2), "promise_amount": 1000,
        })
        self.assertEqual(promise.promise_status, "open")
        self.assertEqual(loan.last_contact_kind, "promise")
        self.assertEqual(loan.open_promise_date, self.today + timedelta(days=2))
        promise.with_user(self.collections).action_kept()
        self.assertEqual(promise.promise_status, "kept")
        self.assertFalse(loan.open_promise_date)

    def test_reminder_sms(self):
        self.env.company.mfi_repay_paybill = "123456"
        loan = self._active(self._new_loan(), days_ago=5)
        self.assertIn("Dear Test,", loan.reminder_sms)
        self.assertIn(f"Paybill 123456, account {loan.name}", loan.reminder_sms)
        self.assertIn("(4 days)", loan.reminder_sms)

    def test_unlock_phone_is_recorded(self):
        loan = self._active(self._new_loan(), days_ago=5)
        with self.assertRaises(AccessError):
            loan.with_user(self.auditor).action_unlock_phone()
        result = loan.with_user(self.collections).action_unlock_phone()
        self.assertIn("0712345678", result["params"]["message"])
        self.assertIn("unlocked by", loan.message_ids[0].body)

    def test_ageing_bucket(self):
        loan = self._active(self._new_loan(), days_ago=5)
        self.assertEqual(loan.ageing_bucket, "1_7")
        loan._update_health(today=self.today + timedelta(days=10))
        self.assertEqual(loan.ageing_bucket, "8_14")

    # ------------------------------------------------------------------
    # Dashboard and reports
    # ------------------------------------------------------------------

    def test_dashboard_par(self):
        late = self._active(self._new_loan(), days_ago=10)  # 9 days past due
        other = self._new_client("Second Borrower", "23456789", "0798765432")
        current = self._active(self._new_loan(client=other))  # disbursed today
        board = self.env["mfi.dashboard"].with_user(self.ceo).create({})
        total = late.outstanding + current.outstanding
        self.assertEqual(board.active_count, 2)
        self.assertAlmostEqual(board.par_1, round(late.outstanding / total * 100, 2), places=2)
        self.assertAlmostEqual(board.par_7, board.par_1, places=2)
        self.assertEqual(board.par_30, 0)
        self.assertEqual(board.arrears_count, 1)

    def test_income_report(self):
        loan = self._active(self._new_loan())  # fees 1,920; interest 3,000 of 13,000
        self._pay(loan, 1300, "INC1")
        wizard = self.env["mfi.report.wizard"].with_user(self.ceo).create({
            "report": "income", "date_from": self.today, "date_to": self.today})
        self.assertEqual(wizard.fees_charged, 1920)
        self.assertAlmostEqual(wizard.interest_collected, 300, places=2)  # 1,300 x 3,000 / 13,000
        self.assertEqual(wizard.penalty_collected, 0)
        self.assertAlmostEqual(wizard.income_total, 2220, places=2)

    def test_report_lists_open(self):
        self._active(self._new_loan())
        for report in ("portfolio", "arrears", "disbursements", "collections", "clients"):
            wizard = self.env["mfi.report.wizard"].with_user(self.ceo).create({"report": report})
            action = wizard.action_show()
            self.assertEqual(action["type"], "ir.actions.act_window", report)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def test_fees_upfront_switch(self):
        self.env.company.mfi_first_loan_fees_upfront = False
        loan = self._new_loan()
        self.assertTrue(loan.is_first_loan)
        self.assertEqual(loan.upfront_total, 0)
        self.assertEqual(loan.deducted_total, 1920)

    def test_loan_number(self):
        self.assertTrue(self._new_loan().name.startswith("RC-L-"))
