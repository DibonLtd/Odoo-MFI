from datetime import timedelta

from odoo import api, fields, models

from ..models.rules import r2

REPORTS = [
    ("portfolio", "Active portfolio"),
    ("arrears", "Arrears & overdue ageing"),
    ("disbursements", "Disbursements"),
    ("collections", "Collections"),
    ("income", "Income summary"),
    ("clients", "Clients onboarded"),
]


class MfiReportWizard(models.TransientModel):
    """The portal's six reports over a date range. The lists can be exported to
    Excel or CSV from Odoo's list view (select the rows, then Export)."""

    _name = "mfi.report.wizard"
    _description = "Microfinance reports"

    report = fields.Selection(REPORTS, required=True, default="portfolio")
    date_from = fields.Date("From", required=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date("To", required=True, default=fields.Date.context_today)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    fees_charged = fields.Monetary("Fees charged on disbursements", compute="_compute_income")
    interest_collected = fields.Monetary(
        "Interest collected", compute="_compute_income",
        help="The interest share of instalments paid: each payment to instalments times the loan's "
        "interest over its total repayable.")
    penalty_collected = fields.Monetary("Default interest collected", compute="_compute_income")
    income_total = fields.Monetary("Total", compute="_compute_income")

    @api.depends("date_from", "date_to", "report")
    def _compute_income(self):
        for wizard in self:
            loans = self.env["mfi.loan"].search([
                ("disbursed_date", ">=", wizard.date_from), ("disbursed_date", "<=", wizard.date_to)])
            payments = self.env["mfi.payment"].search([
                ("state", "=", "allocated"), ("date", ">=", wizard.date_from), ("date", "<=", wizard.date_to)])
            fees = r2(sum(loans.mapped("total_charges")))
            interest = r2(sum(
                p.to_installments * (p.loan_id.interest / p.loan_id.total_repayable)
                for p in payments if p.loan_id.total_repayable > 0
            ))
            penalty = r2(sum(payments.mapped("to_penalty")))
            wizard.update({
                "fees_charged": fees, "interest_collected": interest,
                "penalty_collected": penalty, "income_total": r2(fees + interest + penalty),
            })

    def _list(self, model, domain, list_view):
        name = dict(REPORTS)[self.report]
        if self.report not in ("portfolio", "arrears"):  # those two are as at today
            name = f"{name} · {self.date_from} to {self.date_to}"
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "view_mode": "list,form",
            "views": [(self.env.ref(list_view).id, "list"), (False, "form")],
            "domain": domain,
            "context": {"create": False},
        }

    def action_show(self):
        self.ensure_one()
        day_after = fields.Datetime.to_datetime(self.date_to + timedelta(days=1))
        start = fields.Datetime.to_datetime(self.date_from)
        if self.report == "portfolio":
            return self._list("mfi.loan", [("state", "=", "active")], "mfi_loan.mfi_loan_view_list_portfolio")
        if self.report == "arrears":
            return self._list("mfi.loan", [("state", "=", "active"), ("health", "in", ("arrears", "overdue"))],
                              "mfi_loan.mfi_loan_view_list_arrears")
        if self.report == "disbursements":
            return self._list("mfi.loan",
                              [("disbursed_date", ">=", self.date_from), ("disbursed_date", "<=", self.date_to)],
                              "mfi_loan.mfi_loan_view_list_disbursements")
        if self.report == "collections":
            return self._list("mfi.payment", [("date", ">=", self.date_from), ("date", "<=", self.date_to)],
                              "mfi_loan.mfi_payment_view_list")
        if self.report == "clients":
            return self._list("res.partner", [("is_mfi_client", "=", True), ("create_date", ">=", start),
                                              ("create_date", "<", day_after)],
                              "mfi_loan.mfi_client_view_list")
        # Income stays on this form.
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}
