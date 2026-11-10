from datetime import timedelta
from urllib.parse import unquote

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.sms.tests.common import SMSCase

from .common import MfiCase


@tagged("post_install", "-at_install")
class TestControls(MfiCase, SMSCase):
    """The audit log, viewing personal details, messages to clients and session settings."""

    def _actions(self, record):
        return self.env["mfi.audit.log"].search(
            [("res_model", "=", record._name), ("res_id", "=", record.id)], order="id").mapped("action")

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def test_audit_trail_of_a_loan(self):
        loan = self._active(self._new_loan(), days_ago=3)
        payment = self._pay(loan, 1000, "AUD1")
        actions = self._actions(loan)
        self.assertEqual(actions.count("document.uploaded"), 2)
        self.assertEqual([a for a in actions if a != "document.uploaded"], [
            "loan.created", "loan.sent_to_officer", "loan.agreement_generated", "loan.submitted",
            "loan.approved", "loan.approved", "loan.approved", "loan.disbursed",
        ])
        self.assertEqual(self._actions(payment), ["payment.recorded"])
        entry = self.env["mfi.audit.log"].search([("action", "=", "loan.disbursed"), ("res_id", "=", loan.id)])
        self.assertEqual(entry.user_id, self.finance)
        self.assertIn("mpesa", entry.detail)

    def test_audit_log_access(self):
        self._new_loan()
        Log = self.env["mfi.audit.log"]
        self.assertTrue(Log.with_user(self.auditor).search_count([]))
        self.assertTrue(Log.with_user(self.ceo).search_count([]))
        with self.assertRaises(AccessError):
            Log.with_user(self.finance).search([])
        entry = Log.search([], limit=1)
        with self.assertRaises(UserError):
            entry.write({"action": "changed"})
        with self.assertRaises(UserError):
            entry.unlink()
        with self.assertRaises((AccessError, UserError)):
            Log.with_user(self.admin).create({"action": "made.up"})

    def test_client_changes_are_audited(self):
        self.client.with_user(self.officer).write({"mfi_alt_phone": "0733000111"})
        entry = self.env["mfi.audit.log"].search(
            [("action", "=", "client.updated"), ("res_id", "=", self.client.id)], limit=1)
        self.assertIn("Alternate phone", entry.detail)
        self.assertNotIn("0733000111", entry.detail)

    # ------------------------------------------------------------------
    # Personal details
    # ------------------------------------------------------------------

    def test_personal_details_need_password(self):
        self.assertEqual(self.client.mfi_id_masked, "•••••678")
        action = self.client.with_user(self.ceo).action_mfi_reveal()
        wizard = self.env["mfi.client.reveal.wizard"].with_user(self.ceo).browse(action["res_id"])
        self.assertFalse(wizard.is_shown)
        self.assertFalse(wizard.details_html)
        with self.assertRaisesRegex(UserError, "Incorrect password"):
            wizard.with_context(password="wrong").action_reveal()
        self.assertEqual(self._actions(self.client)[-1], "pii.view_denied")
        wizard.with_context(password="mfi_ceo").action_reveal()
        wizard.invalidate_recordset()
        self.assertTrue(wizard.is_shown)
        self.assertIn("12345678", wizard.details_html)
        self.assertEqual(self._actions(self.client)[-1], "pii.viewed")
        self.assertFalse(wizard.can_correct)  # the CEO does not edit clients

    def test_wrong_passwords_lock(self):
        wizard = self.env["mfi.client.reveal.wizard"].with_user(self.officer).create({"partner_id": self.client.id})
        for _attempt in range(5):
            with self.assertRaisesRegex(UserError, "Incorrect password"):
                wizard.with_context(password="wrong").action_reveal()
        with self.assertRaisesRegex(UserError, "Too many wrong passwords"):
            wizard.with_context(password="mfi_officer").action_reveal()

    def test_correct_id_number(self):
        wizard = self.env["mfi.client.reveal.wizard"].with_user(self.officer).create({"partner_id": self.client.id})
        wizard.with_context(password="mfi_officer").action_reveal()
        wizard.invalidate_recordset()
        self.assertTrue(wizard.can_correct)
        wizard.new_id_number = "12345679"
        wizard.action_save_id_number()
        self.assertEqual(self.client.sudo().mfi_id_number, "12345679")

    # ------------------------------------------------------------------
    # Messages to clients
    # ------------------------------------------------------------------

    def test_reminder_sms(self):
        current = self._active(self._new_loan())
        with self.assertRaisesRegex(UserError, "not in arrears"):
            current.with_user(self.collections).action_send_reminder_sms()
        other = self._new_client("Late Borrower", "23456789", "0798765432")
        late = self._active(self._new_loan(client=other), days_ago=5)
        with self.assertRaises(AccessError):
            late.with_user(self.finance).action_send_reminder_sms()
        with self.mockSMSGateway():
            late.with_user(self.collections).action_send_reminder_sms()
        self.assertEqual(late.last_contact_kind, "sms")
        sms = self.env["sms.sms"].search([("number", "=", "+254798765432")])
        self.assertTrue(sms)
        self.assertIn(late.name, sms[0].body)
        self.assertIn("reminder.sms_sent", self._actions(late))

    def test_whatsapp_reminder_link(self):
        late = self._active(self._new_loan(), days_ago=5)
        action = late.with_user(self.collections).action_whatsapp_reminder()
        self.assertTrue(action["url"].startswith("https://wa.me/254712345678?text="))
        self.assertIn("Dear Test,", unquote(action["url"]))
        self.assertEqual(late.last_contact_kind, "whatsapp")

    def test_agreement_by_email(self):
        self.env.company.email = "loans@example.com"
        loan = self._new_loan()
        loan.action_submit()
        with self.assertRaisesRegex(UserError, "Generate the agreement first"):
            loan.with_user(self.officer).action_send_agreement_email()
        loan.with_user(self.officer).action_generate_agreement()
        action = loan.with_user(self.officer).action_send_agreement_email()
        composer = self.env["mail.compose.message"].with_user(self.officer).with_context(action["context"]).create({})
        self.assertIn(loan.name, composer.subject)
        composer.action_send_mail()
        self.assertEqual(loan.agreement_sent_via, "email")
        self.assertTrue(loan.agreement_sent_at)
        self.assertTrue(loan.message_ids[0].attachment_ids)
        self.assertIn("loan.agreement_sent", self._actions(loan))

    def test_agreement_by_whatsapp(self):
        loan = self._new_loan()
        loan.action_submit()
        loan.with_user(self.officer).action_generate_agreement()
        action = loan.with_user(self.officer).action_send_agreement_whatsapp()
        self.assertTrue(action["url"].startswith("https://wa.me/254712345678?text="))
        self.assertEqual(loan.agreement_sent_via, "whatsapp")

    # ------------------------------------------------------------------
    # Settings and dates
    # ------------------------------------------------------------------

    def test_session_settings(self):
        params = self.env["ir.config_parameter"].sudo()
        self.assertEqual(params.get_param("mfi_loan.session_idle_minutes"), "60")
        self.assertEqual(params.get_param("mfi_loan.session_max_hours"), "10")
        self.env["res.config.settings"].create({"mfi_session_idle_minutes": 30}).execute()
        self.assertEqual(params.get_param("mfi_loan.session_idle_minutes"), "30")

    def test_repaid_on_the_payment_date(self):
        loan = self._active(self._new_loan(), days_ago=5)
        yesterday = self.today - timedelta(days=1)
        self._pay(loan, loan.total_repayable + 100, "FULL1", date=yesterday)
        self.assertEqual(loan.state, "repaid")
        self.assertEqual(loan.closed_date, yesterday)
