from datetime import timedelta

from freezegun import freeze_time

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
                self._new_client("Another Client", "99999999", **({"phone": "0711111111"} | extra))

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

    def test_promise_to_pay_is_an_activity(self):
        loan = self._active(self._new_loan(), days_ago=5)
        promise_type = self.env.ref("mfi_loan.mail_activity_promise")
        loan.with_user(self.collections).activity_schedule(
            activity_type_id=promise_type.id, date_deadline=self.today + timedelta(days=2),
            summary="Will pay KES 1,000 on Friday", user_id=self.collections.id)
        promises = self.env["mail.activity"].search([("res_model", "=", "mfi.loan"),
                                                     ("activity_type_id", "=", promise_type.id)])
        self.assertEqual(promises.res_id, loan.id)
        self.assertEqual(promises.state, "planned")
        with freeze_time(self.today + timedelta(days=3)):
            promises.invalidate_recordset(["state"])
            self.assertEqual(promises.state, "overdue")  # not kept

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
        with freeze_time(self.today + timedelta(days=10)):
            loan._mfi_refresh()
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

    def test_income_in_accounting(self):
        """Income is Accounting's: interest, fees and default interest by account and product."""
        loan = self._active(self._new_loan())
        company = loan.company_id
        lines = self.env["account.move.line"].search([("move_id.mfi_loan_id", "=", loan.id),
                                                      ("parent_state", "=", "posted")])
        def credited(account):
            return sum(lines.filtered(lambda l: l.account_id == account).mapped("credit"))
        self.assertEqual(credited(company.mfi_interest_account_id), 3000)
        self.assertEqual(credited(company.mfi_fee_account_id), 1920)  # 600 upfront + 1,320 deducted
        self.assertEqual(lines.filtered(lambda l: l.account_id == company.mfi_interest_account_id).product_id,
                         loan.product_id.interest_product_id)  # by loan type

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
