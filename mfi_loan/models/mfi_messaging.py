"""Messages to borrowers: reminder SMS, WhatsApp, and the loan agreement by email.

SMS goes through Odoo's SMS (`sms` module), so whichever gateway the database
uses carries it: Odoo IAP credits, or a local gateway module such as Dibon's
SMS gateway connector. WhatsApp works as on the portal: a wa.me link opens
WhatsApp with the message filled in, and the officer sends it.
"""

from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import rules


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _mfi_messaging_blocked(self):
        """True when no message may go to this client (e.g. sample data)."""
        self.ensure_one()
        return False


class ResCompany(models.Model):
    _inherit = "res.company"

    mfi_auto_sms_reminders = fields.Boolean(
        "Send reminder SMS automatically",
        help="Each morning, send the reminder SMS to every client in arrears who has not had one that day.")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mfi_auto_sms_reminders = fields.Boolean(related="company_id.mfi_auto_sms_reminders", readonly=False)


class MfiLoan(models.Model):
    _inherit = "mfi.loan"

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------

    def _mfi_reminder_target(self):
        """The number to message as 2547XXXXXXXX, or why not."""
        self.ensure_one()
        if self.state != "active" or self.health not in ("arrears", "overdue"):
            return False, self.env._("%s is not in arrears.", self.name)
        if self.partner_id._mfi_messaging_blocked():
            return False, self.env._("%s: messages to this client are switched off.", self.name)
        msisdn = rules.kenyan_msisdn(self.partner_id.phone)
        if not msisdn:
            return False, self.env._("%s: the client's phone number is not a Kenyan mobile number.", self.name)
        return msisdn, None

    def _mfi_send_reminder_sms(self):
        """Send the reminder SMS to each loan; returns (sent loans, reasons skipped)."""
        sent, skipped = self.browse(), []
        Note = self.env["mfi.collection.note"]
        for loan in self:
            msisdn, problem = loan._mfi_reminder_target()
            if problem:
                skipped.append(problem)
                continue
            partner = loan.partner_id
            loan._message_sms(loan.reminder_sms, partner_ids=partner.ids,
                              sms_pid_to_number={partner.id: "+" + msisdn})
            Note.create({"loan_id": loan.id, "kind": "sms", "note": loan.reminder_sms})
            rules.audit(self.env, "reminder.sms_sent", loan, {"to": partner.phone})
            sent |= loan
        return sent, skipped

    def action_send_reminder_sms(self):
        rules.check(self.env, "collections.write")
        sent, skipped = self._mfi_send_reminder_sms()
        if not sent and skipped:
            raise UserError("\n".join(skipped))
        message = self.env._("Reminder SMS sent to %s client(s).", len(sent))
        if skipped:
            message += " " + self.env._("Not sent: %s", "; ".join(skipped))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": "success" if not skipped else "warning",
                       "sticky": bool(skipped), "next": {"type": "ir.actions.act_window_close"}},
        }

    def action_whatsapp_reminder(self):
        """Open WhatsApp with the reminder filled in, as the portal does."""
        rules.check(self.env, "collections.write")
        self.ensure_one()
        msisdn, problem = self._mfi_reminder_target()
        if problem:
            raise UserError(problem)
        self.env["mfi.collection.note"].create({"loan_id": self.id, "kind": "whatsapp", "note": self.reminder_sms})
        rules.audit(self.env, "reminder.whatsapp_opened", self, {"to": self.partner_id.phone})
        return {"type": "ir.actions.act_url", "target": "new",
                "url": f"https://wa.me/{msisdn}?text={quote(self.reminder_sms)}"}

    @api.model
    def _cron_send_reminders(self):
        today = fields.Date.context_today(self)
        for company in self.env["res.company"].search([("mfi_auto_sms_reminders", "=", True)]):
            loans = self.search([
                ("company_id", "=", company.id), ("state", "=", "active"),
                ("health", "in", ("arrears", "overdue")),
                ("collection_note_ids", "not any", [("kind", "=", "sms"), ("create_date", ">=", today)]),
            ])
            loans.sudo()._mfi_send_reminder_sms()

    @api.model
    def _cron_daily(self):
        super()._cron_daily()
        self._cron_send_reminders()

    # ------------------------------------------------------------------
    # The agreement
    # ------------------------------------------------------------------

    def _mfi_check_agreement_ready(self):
        rules.check(self.env, "loans.create")
        self.ensure_one()
        if not self.agreement_generated_at:
            raise UserError(self.env._("Generate the agreement first."))
        if self.state not in ("draft", "pending_information"):
            raise UserError(self.env._("The agreement is sent before approval."))

    def _mfi_mark_agreement_sent(self, via):
        for loan in self:
            loan.sudo().write({"agreement_sent_at": fields.Datetime.now(), "agreement_sent_via": via})
            rules.audit(self.env, "loan.agreement_sent", loan, {"via": via})

    def action_send_agreement_email(self):
        """Email the agreement PDF to the client from the company address."""
        self._mfi_check_agreement_ready()
        if self.partner_id._mfi_messaging_blocked():
            raise UserError(self.env._("Messages to this client are switched off."))
        if not self.partner_id.email:
            raise UserError(self.env._("The client has no email address."))
        template = self.env.ref("mfi_loan.mail_template_loan_agreement")
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Send agreement"),
            "res_model": "mail.compose.message",
            "views": [(False, "form")],
            "target": "new",
            "context": {
                "default_model": "mfi.loan",
                "default_res_ids": self.ids,
                "default_composition_mode": "comment",
                "default_template_id": template.id,
                "default_email_layout_xmlid": "mail.mail_notification_light",
                "mfi_mark_agreement_sent": True,
            },
        }

    def message_post(self, **kwargs):
        if self.env.context.get("mfi_mark_agreement_sent") and kwargs.get("message_type") != "notification":
            self.filtered(lambda loan: not loan.agreement_sent_at)._mfi_mark_agreement_sent("email")
        return super().message_post(**kwargs)

    def action_send_agreement_whatsapp(self):
        """Open WhatsApp to the client; the officer attaches the agreement PDF there."""
        self._mfi_check_agreement_ready()
        if self.partner_id._mfi_messaging_blocked():
            raise UserError(self.env._("Messages to this client are switched off."))
        msisdn = rules.kenyan_msisdn(self.partner_id.phone)
        if not msisdn:
            raise UserError(self.env._("The client's phone number is not a Kenyan mobile number."))
        first_name = (self.partner_id.name or "").split(" ")[0]
        text = self.env._(
            "Dear %(name)s, your loan agreement %(loan)s for KES %(amount)s with %(company)s is ready. "
            "Please read it, sign it and send it back to us.",
            name=first_name, loan=self.name, amount=f"{self.principal:,.0f}", company=self.company_id.name)
        self._mfi_mark_agreement_sent("whatsapp")
        return {"type": "ir.actions.act_url", "target": "new", "url": f"https://wa.me/{msisdn}?text={quote(text)}"}
