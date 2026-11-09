from datetime import timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import MfiCase


@tagged("post_install", "-at_install")
class TestLoan(MfiCase):
    """The rules of the Roan Capital portal, as mfi_loan implements them."""

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def test_quote_first_loan(self):
        loan = self._new_loan()
        self.assertTrue(loan.is_first_loan)
        self.assertEqual(loan.interest, 3000)  # 10,000 x 1% x 30 days
        self.assertEqual(loan.total_repayable, 13000)
        self.assertEqual(loan.installment, 434)  # 13,000 / 30, rounded up
        self.assertEqual(loan.upfront_total, 600)  # membership 100 + application 500
        self.assertEqual(loan.deducted_total, 1320)  # LIF 200 + remittance 120 + chattels 1,000
        self.assertEqual(loan.net_disbursement, 8680)

    def test_fees_follow_principal(self):
        loan = self._new_loan(principal=25000)
        fees = {(line.name, line.amount) for line in loan.fee_line_ids}
        self.assertIn(("Loan application fee", 1000), fees)
        self.assertNotIn(("Loan application fee", 500), fees)

    def test_principal_out_of_range(self):
        with self.assertRaises(ValidationError):
            self._new_loan(principal=200000)

    def test_next_loan_is_not_first(self):
        self._active(self._new_loan())
        second = self._new_loan()
        self.assertFalse(second.is_first_loan)
        self.assertEqual(second.upfront_total, 0)
        self.assertNotIn("membership", second.fee_line_ids.fee_id.mapped("code"))

    # ------------------------------------------------------------------
    # Application gates
    # ------------------------------------------------------------------

    def test_submit_needs_guarantor_and_security(self):
        loan = self.env["mfi.loan"].with_user(self.officer).create({
            "partner_id": self.client.id, "product_id": self.logbook.id, "principal": 20000,
        })
        with self.assertRaisesRegex(UserError, "Guarantor"):
            loan.action_submit()
        loan.write({"guarantor_name": "G", "guarantor_id_number": "1", "guarantor_phone": "0700000000"})
        with self.assertRaisesRegex(UserError, "vehicle"):
            loan.action_submit()
        loan.write({"vehicle_reg_no": "KDA 1A", "vehicle_make": "Toyota", "vehicle_model": "Vitz",
                    "vehicle_year": "2015"})
        loan.action_submit()
        self.assertEqual(loan.state, "pending_information")

    def test_send_for_approval_lists_what_is_missing(self):
        loan = self._new_loan()
        loan.action_submit()
        with self.assertRaisesRegex(UserError, "House visit"):
            loan.action_send_for_approval()

    def test_only_originators_capture(self):
        with self.assertRaises(AccessError):
            self._new_loan(by=self.finance)
        self.assertTrue(self._new_loan(by=self.head_office))

    # ------------------------------------------------------------------
    # Approvals: credit manager, credit manager, CEO; Super Admin any stage
    # ------------------------------------------------------------------

    def test_full_approval(self):
        loan = self._new_loan()
        self._approved(loan)
        self.assertEqual(loan.state, "approved")
        self.assertEqual(len(loan.approval_ids), 3)

    def test_nobody_acts_twice(self):
        loan = self._new_loan()
        self._ready(loan)
        loan.with_user(self.cm1).action_approve()
        with self.assertRaisesRegex(UserError, "already acted"):
            loan.with_user(self.cm1).action_approve()

    def test_creator_cannot_approve(self):
        loan = self._new_loan(by=self.cm1)
        self._ready(loan.with_user(self.cm1))
        with self.assertRaisesRegex(UserError, "maker-checker"):
            loan.with_user(self.cm1).action_approve()

    def test_stage_needs_its_role(self):
        loan = self._new_loan()
        self._ready(loan)
        with self.assertRaises(UserError):
            loan.with_user(self.head_office).action_approve()
        loan.with_user(self.cm1).action_approve()
        loan.with_user(self.cm2).action_approve()
        with self.assertRaises(UserError):
            loan.with_user(self.cm1).action_approve()
        loan.with_user(self.admin).action_approve()  # Super Admin may decide any stage
        self.assertEqual(loan.state, "approved")

    def test_awaiting_me(self):
        loan = self._new_loan()
        self._ready(loan)
        Loan = self.env["mfi.loan"]
        self.assertIn(loan, Loan.with_user(self.cm1).search([("awaiting_me", "=", True)]))
        self.assertNotIn(loan, Loan.with_user(self.ceo).search([("awaiting_me", "=", True)]))
        loan.with_user(self.cm1).action_approve()
        self.assertNotIn(loan, Loan.with_user(self.cm1).search([("awaiting_me", "=", True)]))

    def test_reject_needs_reason_and_reopens(self):
        loan = self._new_loan()
        self._ready(loan)
        with self.assertRaises(UserError):
            loan.with_user(self.cm1).action_reject("")
        loan.with_user(self.cm1).action_reject("Insufficient collateral")
        self.assertEqual(loan.state, "rejected")
        loan.action_reopen()
        self.assertEqual(loan.state, "draft")

    # ------------------------------------------------------------------
    # Disbursement and the schedule
    # ------------------------------------------------------------------

    def test_disbursement_rights(self):
        loan = self._new_loan()
        self._approved(loan)
        with self.assertRaises(AccessError):
            loan.with_user(self.officer).action_disburse("mpesa", "SBX123")
        loan.with_user(self.head_office).action_disburse("mpesa", "SBX123")
        self.assertEqual(loan.state, "active")

    def test_creator_cannot_disburse(self):
        loan = self._new_loan(by=self.head_office)
        self._approved(loan.with_user(self.head_office))
        with self.assertRaises(AccessError):
            loan.with_user(self.head_office).action_disburse("mpesa", "SBX999")

    def test_schedule(self):
        loan = self._active(self._new_loan())
        schedule = loan.installment_ids.sorted("seq")
        self.assertEqual(len(schedule), 30)
        self.assertEqual(loan.start_date, self.today + timedelta(days=1))
        self.assertEqual(loan.maturity_date, self.today + timedelta(days=30))
        self.assertEqual(schedule[0].due_date, loan.start_date)
        self.assertEqual(set(schedule[:-1].mapped("amount_due")), {434})
        self.assertEqual(schedule[-1].amount_due, 414)  # 13,000 - 29 x 434
        self.assertEqual(sum(schedule.mapped("amount_due")), 13000)
        self.assertEqual(loan.health, "current")

    # ------------------------------------------------------------------
    # Default interest, arrears and payments
    # ------------------------------------------------------------------

    def test_default_interest_and_arrears(self):
        loan = self._active(self._new_loan(), days_ago=5)
        # Due before each day: 1, 2, 3, 4 instalments of 434 at 1% a day
        self.assertAlmostEqual(loan.penalty_accrued, 4.34 * (1 + 2 + 3 + 4), places=2)
        self.assertEqual(loan.health, "arrears")
        self.assertEqual(loan.arrears_amount, 4 * 434)
        self.assertEqual(loan.days_past_due, 4)
        self.assertAlmostEqual(loan.outstanding, 13000 + 43.40, places=2)

    def test_overdue_after_maturity(self):
        loan = self._active(self._new_loan(term="two_weeks"))
        loan._update_health(today=loan.maturity_date + timedelta(days=3))
        self.assertEqual(loan.health, "overdue")

    def test_payment_pays_default_interest_first_then_in_order(self):
        loan = self._active(self._new_loan(), days_ago=5)
        payment = self._pay(loan, 1000, "pay001")
        self.assertAlmostEqual(payment.to_penalty, 43.40, places=2)
        self.assertAlmostEqual(payment.to_installments, 956.60, places=2)
        first, second, third = loan.installment_ids.sorted("seq")[:3]
        self.assertEqual((first.amount_paid, second.amount_paid), (434, 434))
        self.assertAlmostEqual(third.amount_paid, 88.60, places=2)

    def test_full_payment_repays(self):
        loan = self._active(self._new_loan())
        self._pay(loan, 13000, "pay001")
        self.assertEqual(loan.state, "repaid")
        self.assertEqual(loan.outstanding, 0)

    def test_who_records_payments(self):
        loan = self._active(self._new_loan())
        self._pay(loan, 500, "pay001", by=self.collections)
        self._pay(loan, 500, "pay002", by=self.officer)
        with self.assertRaises(AccessError):
            self._pay(loan, 500, "pay003", by=self.auditor)

    def test_reference_rules(self):
        loan = self._active(self._new_loan())
        with self.assertRaises(UserError):
            self.env["mfi.payment"].with_user(self.finance).create(
                {"loan_id": loan.id, "amount": 500, "method": "mpesa"})
        self._pay(loan, 500, "ABC123")
        with self.assertRaisesRegex(UserError, "already recorded"):
            self._pay(loan, 500, "abc123")

    def test_unmatched_lookup_and_match(self):
        loan = self._active(self._new_loan())
        Payment = self.env["mfi.payment"].with_user(self.finance)
        by_phone = Payment.create({"amount": 500, "method": "mpesa", "reference": "P1", "lookup": "254712345678"})
        self.assertEqual(by_phone.loan_id, loan)
        self.assertEqual(by_phone.state, "allocated")
        stray = Payment.create({"amount": 500, "method": "mpesa", "reference": "P2", "lookup": "nobody"})
        self.assertEqual(stray.state, "unmatched")
        stray.action_match(loan)
        self.assertEqual(stray.state, "allocated")
        self.assertEqual(loan.amount_paid, 1000)

    def test_reversal_reapplies_and_reopens(self):
        loan = self._active(self._new_loan())
        first = self._pay(loan, 500, "P1")
        self._pay(loan, 12500, "P2")
        self.assertEqual(loan.state, "repaid")
        with self.assertRaises(AccessError):
            first.with_user(self.officer).action_reverse("Bounced")
        first.with_user(self.finance).action_reverse("Bounced")
        self.assertEqual(first.state, "reversed")
        self.assertEqual(loan.state, "active")
        self.assertEqual(loan.amount_paid, 12500)

    def test_recorded_payment_is_locked(self):
        loan = self._active(self._new_loan())
        payment = self._pay(loan, 500, "P1")
        with self.assertRaises(UserError):
            payment.sudo().write({"amount": 1})

    # ------------------------------------------------------------------
    # Early settlement and write-off
    # ------------------------------------------------------------------

    def test_settlement_quote_and_settle(self):
        loan = self._active(self._new_loan(), days_ago=4)
        settlement = loan._settlement_quote()
        # 4 days since the first instalment, raised to the 14-day minimum
        self.assertEqual(settlement["interest_days"], 14)
        self.assertEqual(settlement["interest"], 1400)
        self.assertEqual(settlement["new_total_payable"], 11400)
        self.assertAlmostEqual(settlement["penalty_due"], 4.34 * (1 + 2 + 3), places=2)
        self.assertAlmostEqual(settlement["settlement_amount"], 11400 + 26.04, places=2)
        with self.assertRaisesRegex(UserError, "at least"):
            loan.with_user(self.finance).action_settle(11000, "mpesa", "SET1")
        loan.with_user(self.finance).action_settle(settlement["settlement_amount"], "mpesa", "SET2")
        self.assertEqual(loan.state, "repaid")
        self.assertEqual(loan.total_repayable, 11400)

    def test_write_off(self):
        loan = self._active(self._new_loan())
        with self.assertRaises(AccessError):
            loan.with_user(self.finance).action_write_off("Borrower absconded")
        with self.assertRaises(UserError):
            loan.with_user(self.ceo).action_write_off("no")
        loan.with_user(self.ceo).action_write_off("Borrower absconded")
        self.assertEqual(loan.state, "written_off")

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------

    def test_blacklist_rights_and_reason(self):
        with self.assertRaises(AccessError):
            self.client.with_user(self.officer).write({"mfi_blacklisted": True, "mfi_blacklist_reason": "Fraud"})
        with self.assertRaises(UserError):
            self.client.with_user(self.cm1).write({"mfi_blacklisted": True})
        self.client.with_user(self.cm1).write({"mfi_blacklisted": True, "mfi_blacklist_reason": "Fraud"})
        with self.assertRaises(UserError):
            self._new_loan().action_submit()
