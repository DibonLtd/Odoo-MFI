from odoo import api, fields, models
from odoo.exceptions import UserError

from . import rules
from .res_partner import mask_phone

CONTACT_KINDS = [
    ("call", "Call"),
    ("visit", "Visit"),
    ("sms", "SMS"),
    ("whatsapp", "WhatsApp"),
    ("promise", "Promise to pay"),
    ("other", "Note"),
]


class MfiCollectionNote(models.Model):
    """One contact with a late borrower: a call, a visit, a message or a promise to pay."""

    _name = "mfi.collection.note"
    _description = "Collections contact"
    _order = "create_date desc, id desc"

    loan_id = fields.Many2one("mfi.loan", required=True, ondelete="cascade", index=True)
    partner_id = fields.Many2one(related="loan_id.partner_id", store=True)
    kind = fields.Selection(CONTACT_KINDS, "Type", required=True, default="call")
    note = fields.Text()
    currency_id = fields.Many2one(related="loan_id.currency_id")
    promise_date = fields.Date()
    promise_amount = fields.Monetary()
    promise_status = fields.Selection(
        [("open", "Open"), ("kept", "Kept"), ("broken", "Broken")], readonly=True)
    user_id = fields.Many2one("res.users", "By", default=lambda self: self.env.user, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        rules.check(self.env, "collections.write")
        for vals in vals_list:
            if vals.get("kind") == "promise":
                if not vals.get("promise_date"):
                    raise UserError(self.env._("Promise date is required."))
                vals["promise_status"] = "open"
            else:
                vals.update(promise_date=False, promise_amount=0, promise_status=False)
            vals["user_id"] = self.env.user.id
        return super().create(vals_list)

    def _set_promise(self, status):
        rules.check(self.env, "collections.write")
        for note in self:
            if note.kind != "promise":
                raise UserError(self.env._("Only a promise to pay can be marked kept or broken."))
            note.sudo().promise_status = status
            note.loan_id.message_post(body=self.env._(
                "Promise to pay of %(date)s marked %(status)s.", date=note.promise_date, status=status))

    def action_kept(self):
        self._set_promise("kept")

    def action_broken(self):
        self._set_promise("broken")


class MfiLoan(models.Model):
    _inherit = "mfi.loan"

    partner_phone = fields.Char(related="partner_id.phone", string="Phone")
    partner_phone_masked = fields.Char(related="partner_id.mfi_phone_masked", string="Client phone")
    guarantor_phone_masked = fields.Char("Guarantor phone", compute="_compute_guarantor_phone_masked")
    collection_note_ids = fields.One2many("mfi.collection.note", "loan_id", "Contacts")
    last_contact_date = fields.Datetime(compute="_compute_last_contact", store=True)
    last_contact_kind = fields.Selection(CONTACT_KINDS, compute="_compute_last_contact", store=True)
    last_contact_note = fields.Char("Last contact", compute="_compute_last_contact", store=True)
    open_promise_date = fields.Date("Promise due", compute="_compute_last_contact", store=True)
    reminder_sms = fields.Text("Reminder SMS", compute="_compute_reminder_sms")

    @api.depends("guarantor_phone")
    def _compute_guarantor_phone_masked(self):
        for loan in self:
            loan.guarantor_phone_masked = mask_phone(loan.guarantor_phone)

    @api.depends("collection_note_ids.create_date", "collection_note_ids.promise_status")
    def _compute_last_contact(self):
        for loan in self:
            notes = loan.collection_note_ids.sorted(lambda n: (n.create_date or fields.Datetime.now(), n.id))
            last = notes[-1:] if notes else notes
            loan.last_contact_date = last.create_date
            loan.last_contact_kind = last.kind
            loan.last_contact_note = (last.note or "")[:120] if last else False
            promises = notes.filtered(lambda n: n.kind == "promise" and n.promise_status == "open")
            loan.open_promise_date = min(promises.mapped("promise_date")) if promises else False

    @api.depends("partner_id.name", "name", "arrears_amount", "days_past_due", "company_id.mfi_repay_paybill")
    def _compute_reminder_sms(self):
        for loan in self:
            first_name = (loan.partner_id.name or "").split(" ")[0]
            paybill = loan.company_id.mfi_repay_paybill
            pay = f" via Paybill {paybill}, account {loan.name}" if paybill else ""
            loan.reminder_sms = (
                f"Dear {first_name}, your {loan.company_id.name} loan {loan.name} has "
                f"KES {loan.arrears_amount:,.0f} in arrears ({loan.days_past_due} days). "
                f"Please pay{pay} today to avoid {loan.penalty_rate * 100:g}% daily default interest. Thank you."
            )

    def action_log_contact(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Log a contact"),
            "res_model": "mfi.collection.note",
            "view_mode": "form",
            "target": "new",
            "context": {"default_loan_id": self.id},
        }

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
