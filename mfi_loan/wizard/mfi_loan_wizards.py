from odoo import api, fields, models

METHODS = [("mpesa", "M-Pesa"), ("bank", "Bank"), ("cash", "Cash")]


def _active_id(self):
    return self.env.context.get("active_id")


class MfiLoanDecide(models.TransientModel):
    _name = "mfi.loan.decide.wizard"
    _description = "Approve or reject a loan stage"

    loan_id = fields.Many2one("mfi.loan", required=True, default=_active_id)
    decision = fields.Selection(
        [("approved", "Approve"), ("rejected", "Reject")],
        required=True, default=lambda self: self.env.context.get("default_decision", "approved"),
    )
    comment = fields.Text(help="Required when rejecting.")

    def action_confirm(self):
        self.ensure_one()
        if self.decision == "approved":
            self.loan_id.action_approve(self.comment or "")
        else:
            self.loan_id.action_reject(self.comment)
        return {"type": "ir.actions.act_window_close"}


class MfiLoanDisburse(models.TransientModel):
    _name = "mfi.loan.disburse.wizard"
    _description = "Disburse a loan"

    loan_id = fields.Many2one("mfi.loan", required=True, default=_active_id)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    net_disbursement = fields.Monetary(related="loan_id.net_disbursement")
    method = fields.Selection(METHODS, required=True, default="mpesa")
    reference = fields.Char(required=True)
    date = fields.Date(required=True, default=fields.Date.context_today)

    def action_confirm(self):
        self.ensure_one()
        self.loan_id.action_disburse(self.method, self.reference, self.date)
        return {"type": "ir.actions.act_window_close"}


class MfiLoanSettle(models.TransientModel):
    _name = "mfi.loan.settle.wizard"
    _description = "Settle a loan early"

    loan_id = fields.Many2one("mfi.loan", required=True, default=_active_id)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    interest_days = fields.Integer(readonly=True)
    interest = fields.Monetary(readonly=True)
    new_total_payable = fields.Monetary(readonly=True)
    amount_paid = fields.Monetary(readonly=True)
    penalty_due = fields.Monetary("Default interest due", readonly=True)
    settlement_amount = fields.Monetary(readonly=True)
    amount = fields.Monetary(required=True)
    method = fields.Selection(METHODS, required=True, default="mpesa")
    reference = fields.Char()

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        loan = self.env["mfi.loan"].browse(values.get("loan_id") or _active_id(self))
        if loan:
            settlement = loan._settlement_quote()
            values.update({k: v for k, v in settlement.items() if k in self._fields})
            values["amount"] = settlement["settlement_amount"]
        return values

    def action_confirm(self):
        self.ensure_one()
        self.loan_id.action_settle(self.amount, self.method, self.reference)
        return {"type": "ir.actions.act_window_close"}


class MfiLoanWriteOff(models.TransientModel):
    _name = "mfi.loan.writeoff.wizard"
    _description = "Write off a loan"

    loan_id = fields.Many2one("mfi.loan", required=True, default=_active_id)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        self.loan_id.action_write_off(self.reason)
        return {"type": "ir.actions.act_window_close"}


class MfiPaymentMatch(models.TransientModel):
    _name = "mfi.payment.match.wizard"
    _description = "Match a payment to a loan"

    payment_id = fields.Many2one("mfi.payment", required=True, default=_active_id)
    loan_id = fields.Many2one("mfi.loan", required=True, domain=[("state", "=", "active")])

    def action_confirm(self):
        self.ensure_one()
        self.payment_id.action_match(self.loan_id)
        return {"type": "ir.actions.act_window_close"}


class MfiPaymentReverse(models.TransientModel):
    _name = "mfi.payment.reverse.wizard"
    _description = "Reverse a payment"

    payment_id = fields.Many2one("mfi.payment", required=True, default=_active_id)
    reason = fields.Char(required=True)

    def action_confirm(self):
        self.ensure_one()
        self.payment_id.action_reverse(self.reason)
        return {"type": "ir.actions.act_window_close"}
