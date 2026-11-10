"""View a client's personal details, as the portal does: confirm your password,
see them for 60 seconds, and the view is recorded in the audit log."""

from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessDenied, UserError

from ..models import rules

SHOW_SECONDS = 60
MAX_WRONG = 5
LOCK_MINUTES = 5


class MfiClientRevealWizard(models.TransientModel):
    _name = "mfi.client.reveal.wizard"
    _description = "View a client's personal details"
    _transient_max_hours = 0.5

    partner_id = fields.Many2one("res.partner", "Client", required=True, readonly=True, ondelete="cascade")
    password = fields.Char(store=False)
    revealed_at = fields.Datetime(readonly=True)
    is_shown = fields.Boolean(compute="_compute_details")
    details_html = fields.Html("Personal details", compute="_compute_details", sanitize=False)
    can_correct = fields.Boolean(compute="_compute_details")
    new_id_number = fields.Char("Correct the ID / registration number")

    @api.depends("revealed_at")
    def _compute_details(self):
        now = fields.Datetime.now()
        for wizard in self:
            shown = bool(
                wizard.revealed_at and wizard.create_uid == self.env.user
                and now - wizard.revealed_at <= timedelta(seconds=SHOW_SECONDS)
            )
            wizard.is_shown = shown
            wizard.can_correct = shown and rules.allowed(self.env, "clients.write")
            wizard.details_html = wizard._details_html() if shown else False

    def _details_html(self):
        client = self.partner_id.sudo()
        rows = [
            (self.env._("ID / registration number"), client.mfi_id_number),
            (self.env._("Phone"), client.phone),
            (self.env._("Alternate phone"), client.mfi_alt_phone),
            (self.env._("Email"), client.email),
            (self.env._("KRA PIN"), client.mfi_kra_pin),
            (self.env._("Bank account"), " ".join(filter(None, [client.mfi_bank_account_name,
                                                                client.mfi_bank_account_number]))),
        ]
        if client.mfi_client_type == "business":
            rows.append((self.env._("Director / contact person"), ", ".join(filter(None, [
                client.mfi_contact_name, client.mfi_contact_id_number, client.mfi_contact_phone]))))
        for kin in client.mfi_next_of_kin_ids:
            rows.append((self.env._("Next of kin (%s)", kin.relationship or "-"),
                         ", ".join(filter(None, [kin.full_name, kin.id_number, kin.phone]))))
        for loan in client.mfi_loan_ids.filtered("guarantor_name"):
            rows.append((self.env._("Guarantor, %s", loan.name),
                         ", ".join(filter(None, [loan.guarantor_name, loan.guarantor_id_number, loan.guarantor_phone]))))
        body = Markup("").join(
            Markup("<tr><th class='pe-3'>%s</th><td>%s</td></tr>") % (label, value or "-") for label, value in rows
        )
        return Markup("<table class='table table-sm'>%s</table>") % body

    def _locked(self):
        """Too many wrong passwords from this user lately."""
        since = fields.Datetime.now() - timedelta(minutes=LOCK_MINUTES)
        Log = self.env["mfi.audit.log"].sudo()
        last_ok = Log.search([("user_id", "=", self.env.uid), ("action", "=", "pii.viewed")], limit=1)
        domain = [("user_id", "=", self.env.uid), ("action", "=", "pii.view_denied"), ("date", ">=", since)]
        if last_ok:
            domain.append(("date", ">", last_ok.date))
        return Log.search_count(domain) >= MAX_WRONG

    def action_reveal(self):
        self.ensure_one()
        if self._locked():
            raise UserError(self.env._("Too many wrong passwords. Try again in a few minutes."))
        password = self.env.context.get("password") or ""
        try:
            self.env.user._check_credentials(
                {"login": self.env.user.login, "password": password, "type": "password"}, {"interactive": True})
        except AccessDenied:
            # The error below rolls this transaction back, so the refusal is logged on its own.
            self.env["mfi.audit.log"].sudo()._log_committed("pii.view_denied", self.partner_id)
            raise UserError(self.env._("Incorrect password.")) from None
        rules.audit(self.env, "pii.viewed", self.partner_id, {
            "fields": "ID number, phones, email, KRA PIN, bank account, contact person, next of kin, guarantors"})
        self.revealed_at = fields.Datetime.now()
        return self._reopen()

    def action_save_id_number(self):
        self.ensure_one()
        rules.check(self.env, "clients.write")
        if not self.is_shown:
            raise UserError(self.env._("Confirm your password again."))
        new = (self.new_id_number or "").strip()
        if not new:
            raise UserError(self.env._("Enter the new number."))
        self.partner_id.sudo().mfi_id_number = new  # the client rules check the format and uniqueness
        self.new_id_number = False
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Personal details"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
        }


class ResPartner(models.Model):
    _inherit = "res.partner"

    mfi_id_masked = fields.Char("ID / registration number", compute="_compute_mfi_id_masked")

    def _compute_mfi_id_masked(self):
        for partner in self:
            number = partner.sudo().mfi_id_number or ""
            partner.mfi_id_masked = f"•••••{number[-3:]}" if number else False

    def action_mfi_reveal(self):
        self.ensure_one()
        wizard = self.env["mfi.client.reveal.wizard"].create({"partner_id": self.id})
        return wizard._reopen()
