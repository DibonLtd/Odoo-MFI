"""Collections on Odoo's own tools (DECISIONS D-017):

* contacts and promises are activities on the loan: Call and Visit, and Promise
  to pay, whose deadline is the promised date (an overdue promise is a broken one);
  what was said goes in the chatter;
* the reminder text is an SMS template; automatic reminders are Accounting's
  follow-up levels on the overdue instalments.

What stays here is only what is ours: masked phones, and unlocking them.
"""

from odoo import api, fields, models

from . import rules
from .res_partner import mask_phone


class MfiLoan(models.Model):
    _inherit = "mfi.loan"

    partner_phone = fields.Char(related="partner_id.phone", string="Phone")
    partner_phone_masked = fields.Char(related="partner_id.mfi_phone_masked", string="Client phone")
    guarantor_phone_masked = fields.Char("Guarantor phone", compute="_compute_guarantor_phone_masked")
    reminder_sms = fields.Text("Reminder SMS", compute="_compute_reminder_sms")

    @api.depends("guarantor_phone")
    def _compute_guarantor_phone_masked(self):
        for loan in self:
            loan.guarantor_phone_masked = mask_phone(loan.guarantor_phone)

    @api.depends("partner_id.name", "name", "arrears_amount", "days_past_due", "company_id.mfi_repay_paybill")
    def _compute_reminder_sms(self):
        template = self.env.ref("mfi_loan.sms_template_loan_reminder", raise_if_not_found=False)
        bodies = template._render_field("body", self.ids) if template and self.ids else {}
        for loan in self:
            loan.reminder_sms = bodies.get(loan.id, "")

    def action_unlock_phone(self):
        """Show the client's and guarantor's numbers, and record who looked."""
        rules.check(self.env, "collections.write")
        self.ensure_one()
        self.message_post(body=self.env._("Phone numbers unlocked by %s.", self.env.user.name))
        rules.audit(self.env, "pii.phone_viewed", self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.partner_id.name,
                "message": self.env._("Client: %(client)s · Guarantor (%(name)s): %(guarantor)s",
                                      client=self.partner_id.phone or "-",
                                      name=self.guarantor_name or "-", guarantor=self.guarantor_phone or "-"),
                "sticky": True,
                "type": "info",
            },
        }
