import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import rules
from .rules import r2

LOCKED_FIELDS = {"loan_id", "amount", "method", "reference", "date", "state",
                 "to_penalty", "to_installments", "overpayment"}


def _phones(text):
    """The forms a phone number may be stored in: 07XXXXXXXX and 2547XXXXXXXX."""
    digits = re.sub(r"\D", "", text or "")
    forms = {digits}
    if len(digits) == 10 and digits.startswith("0"):
        forms.add("254" + digits[1:])
    if len(digits) == 12 and digits.startswith("254"):
        forms.add("0" + digits[3:])
    return {f for f in forms if f}


class MfiPayment(models.Model):
    """A repayment, recorded by hand until M-Pesa and bank feeds are connected."""

    _name = "mfi.payment"
    _description = "Loan repayment"
    _order = "date desc, id desc"

    loan_id = fields.Many2one("mfi.loan", index=True, domain=[("state", "=", "active")],
                              help="Empty while the payment is unmatched.")
    partner_id = fields.Many2one(related="loan_id.partner_id", store=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(required=True)
    method = fields.Selection(
        [("mpesa", "M-Pesa"), ("bank", "Bank"), ("cash", "Cash")], required=True, default="mpesa"
    )
    reference = fields.Char()
    lookup = fields.Char("Account reference", help="Loan S/N, the client's ID number or phone, "
                         "used to find the loan when none is chosen.")
    payer_phone = fields.Char()
    date = fields.Date("Received", required=True, default=fields.Date.context_today)
    note = fields.Char()
    state = fields.Selection(
        [("unmatched", "Unmatched"), ("allocated", "Allocated"), ("reversed", "Reversed")],
        default="unmatched", required=True, readonly=True,
    )
    to_penalty = fields.Monetary("To default interest", readonly=True)
    to_installments = fields.Monetary("To instalments", readonly=True)
    overpayment = fields.Monetary(readonly=True)
    reversal_reason = fields.Char(readonly=True)

    @api.model
    def _lookup_loan(self, text):
        """Find the active loan for a loan S/N, a client's ID number or phone."""
        text = (text or "").strip()
        Loan = self.env["mfi.loan"].sudo()
        if not text:
            return Loan
        phones = _phones(text)
        for loan in Loan.search([("state", "=", "active")], order="id desc"):
            client = loan.partner_id
            if (loan.name.upper() == text.upper() or client.mfi_id_number == text
                    or (phones and _phones(client.phone) & phones)):
                return loan
        return Loan

    @api.model_create_multi
    def create(self, vals_list):
        rules.check(self.env, "payments.record")
        for vals in vals_list:
            vals["reference"] = (vals.get("reference") or "").strip().upper() or False
            if not vals.get("loan_id") and vals.get("lookup"):
                vals["loan_id"] = self._lookup_loan(vals["lookup"]).id or False
            if r2(vals.get("amount") or 0) <= 0:
                raise UserError(self.env._("Amount must be greater than zero."))
            if vals.get("method", "mpesa") != "cash" and not vals["reference"]:
                raise UserError(self.env._("A transaction reference is required for M-Pesa / bank payments."))
            if vals["reference"] and self.sudo().search_count([
                ("method", "=", vals.get("method", "mpesa")), ("reference", "=", vals["reference"]),
            ]):
                raise UserError(self.env._("A payment with this reference was already recorded."))
            vals["state"] = "unmatched"
        payments = super(MfiPayment, self.with_context(mfi_payment_internal=True)).create(vals_list)
        for payment in payments.filtered("loan_id"):
            payment._apply_to(payment.loan_id)
        return payments.with_env(self.env)

    def _apply_to(self, loan):
        self.ensure_one()
        if loan.state != "active":
            raise UserError(self.env._("Payments can only be applied to active loans."))
        loan._accrue_penalty(self.date)
        to_penalty, to_installments, over = loan._allocate(self.amount, self.date)
        self.sudo().with_context(mfi_payment_internal=True).write({
            "loan_id": loan.id, "state": "allocated",
            "to_penalty": to_penalty, "to_installments": to_installments, "overpayment": over,
        })
        loan._close_if_repaid()
        loan._update_health()

    def action_match(self, loan):
        rules.check(self.env, "payments.record")
        self.ensure_one()
        if self.state != "unmatched":
            raise UserError(self.env._("Unmatched payment not found."))
        self._apply_to(loan)
        self.loan_id.message_post(body=self.env._(
            "Payment %(ref)s of KES %(amount)s matched manually.",
            ref=self.reference or self.method, amount=f"{self.amount:,.2f}"))

    def action_reverse(self, reason):
        rules.check(self.env, "payments.reverse")
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise UserError(self.env._("Give a reason."))
        for payment in self:
            if payment.state == "reversed":
                raise UserError(self.env._("Payment not found or already reversed."))
            was = payment.state
            payment.sudo().with_context(mfi_payment_internal=True).write({
                "state": "reversed", "reversal_reason": f"{reason} ({self.env.user.name})",
            })
            if payment.loan_id and was == "allocated":
                payment.loan_id._reallocate()
                payment.loan_id.message_post(body=self.env._(
                    "Payment %(ref)s reversed: %(reason)s", ref=payment.reference or payment.method, reason=reason))

    def write(self, vals):
        if LOCKED_FIELDS & vals.keys() and not self.env.context.get("mfi_payment_internal"):
            raise UserError(self.env._("A recorded payment cannot be changed; reverse it instead."))
        return super().write(vals)

    def _compute_display_name(self):
        for payment in self:
            payment.display_name = f"{payment.reference or payment.method} · KES {payment.amount:,.2f}"
