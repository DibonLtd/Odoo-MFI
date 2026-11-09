from datetime import timedelta

from markupsafe import Markup, escape

from odoo import api, fields, models

from .rules import r2

BUCKETS = [("current", "Current"), ("1_7", "1-7 days"), ("8_14", "8-14 days"),
           ("15_30", "15-30 days"), ("30_plus", "30+ days")]


def _table(headers, rows):
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in rows)
    empty = f'<tr><td colspan="{len(headers)}" class="text-muted">Nothing to show</td></tr>'
    return Markup(f'<table class="table table-sm"><thead><tr>{head}</tr></thead>'
                  f"<tbody>{body or empty}</tbody></table>")


class MfiDashboard(models.TransientModel):
    """The portfolio snapshot, worked out when opened (as the portal's dashboard)."""

    _name = "mfi.dashboard"
    _description = "Microfinance dashboard"

    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    as_of = fields.Date(default=fields.Date.context_today, readonly=True)
    active_count = fields.Integer(compute="_compute_all")
    active_outstanding = fields.Monetary(compute="_compute_all")
    arrears_count = fields.Integer(compute="_compute_all")
    arrears_missed = fields.Monetary("Missed instalments", compute="_compute_all")
    overdue_count = fields.Integer(compute="_compute_all")
    overdue_outstanding = fields.Monetary(compute="_compute_all")
    par_1 = fields.Float("PAR 1 (%)", compute="_compute_all")
    par_7 = fields.Float("PAR 7 (%)", compute="_compute_all")
    par_30 = fields.Float("PAR 30 (%)", compute="_compute_all")
    collected_today = fields.Monetary(compute="_compute_all")
    collected_today_count = fields.Integer(compute="_compute_all")
    due_today = fields.Monetary(compute="_compute_all")
    collected_vs_due_today = fields.Float("Collected / due today (%)", compute="_compute_all")
    disbursed_month = fields.Monetary("Disbursed this month", compute="_compute_all")
    disbursed_month_count = fields.Integer(compute="_compute_all")
    collected_month = fields.Monetary("Collected this month", compute="_compute_all")
    pending_information = fields.Integer(compute="_compute_all")
    pending_approval = fields.Integer(compute="_compute_all")
    to_disburse = fields.Integer(compute="_compute_all")
    clients = fields.Integer(compute="_compute_all")
    clients_new_month = fields.Integer("New this month", compute="_compute_all")
    collection_rate_30 = fields.Float("30-day collection rate (%)", compute="_compute_all")
    ageing_html = fields.Html("Arrears ageing", compute="_compute_all", sanitize=False)
    attention_html = fields.Html("Needs attention", compute="_compute_all", sanitize=False)
    approvals_html = fields.Html("Approval queue", compute="_compute_all", sanitize=False)

    @api.depends("as_of")
    def _compute_all(self):
        Loan, Payment = self.env["mfi.loan"], self.env["mfi.payment"]
        Inst, Partner = self.env["mfi.loan.installment"], self.env["res.partner"]
        for board in self:
            today = board.as_of or fields.Date.context_today(self)
            month_start = today.replace(day=1)
            active = Loan.search([("state", "=", "active")])
            arrears = active.filtered(lambda l: l.health == "arrears")
            overdue = active.filtered(lambda l: l.health == "overdue")
            total = sum(active.mapped("outstanding"))

            def par(days):
                at_risk = sum(active.filtered(lambda l: l.days_past_due >= days).mapped("outstanding"))
                return r2(at_risk / total * 100) if total else 0.0

            paid = Payment.search([("state", "=", "allocated")])
            today_paid = paid.filtered(lambda p: p.date == today)
            due_today = sum(Inst.search([("due_date", "=", today), ("loan_id.state", "=", "active")]).mapped("amount_due"))
            since = today - timedelta(days=29)
            expected_30 = sum(Inst.search([("due_date", ">=", since), ("due_date", "<=", today)]).mapped("amount_due"))
            collected_30 = sum(paid.filtered(lambda p: since <= p.date <= today).mapped("amount"))
            disbursed = Loan.search([("disbursed_date", ">=", month_start), ("disbursed_date", "<=", today)])

            board.update({
                "active_count": len(active),
                "active_outstanding": total,
                "arrears_count": len(arrears),
                "arrears_missed": sum(arrears.mapped("arrears_amount")),
                "overdue_count": len(overdue),
                "overdue_outstanding": sum(overdue.mapped("outstanding")),
                "par_1": par(1), "par_7": par(7), "par_30": par(30),
                "collected_today": sum(today_paid.mapped("amount")),
                "collected_today_count": len(today_paid),
                "due_today": due_today,
                "collected_vs_due_today": r2(sum(today_paid.mapped("amount")) / due_today * 100) if due_today else 0.0,
                "disbursed_month": sum(disbursed.mapped("principal")),
                "disbursed_month_count": len(disbursed),
                "collected_month": sum(paid.filtered(lambda p: p.date >= month_start).mapped("amount")),
                "pending_information": Loan.search_count([("state", "=", "pending_information")]),
                "pending_approval": Loan.search_count([("state", "=", "pending_approval")]),
                "to_disburse": Loan.search_count([("state", "=", "approved")]),
                "clients": Partner.search_count([("is_mfi_client", "=", True)]),
                "clients_new_month": Partner.search_count([
                    ("is_mfi_client", "=", True), ("create_date", ">=", fields.Datetime.to_datetime(month_start))]),
                "collection_rate_30": r2(collected_30 / expected_30 * 100) if expected_30 else 0.0,
                "ageing_html": _table(["Bucket", "Loans", "Outstanding (KES)"], [
                    (label, len(group), f"{sum(group.mapped('outstanding')):,.0f}")
                    for key, label in BUCKETS
                    for group in [active.filtered(lambda l, k=key: l.ageing_bucket == k)]
                ]),
                "attention_html": _table(["Loan", "Client", "Days late", "Outstanding (KES)", "Status"], [
                    (l.name, l.partner_id.name, l.days_past_due, f"{l.outstanding:,.0f}",
                     dict(l._fields["health"].selection)[l.health])
                    for l in (arrears | overdue).sorted("outstanding", reverse=True)[:6]
                ]),
                "approvals_html": _table(["Loan", "Client", "Amount (KES)", "Stage"], [
                    (l.name, l.partner_id.name, f"{l.principal:,.0f}", l.approval_stage)
                    for l in Loan.search([("state", "=", "pending_approval")], order="submitted_at asc, id asc", limit=5)
                ]),
            })

    @api.model
    def action_open(self):
        board = self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Dashboard"),
            "res_model": "mfi.dashboard",
            "res_id": board.id,
            "view_mode": "form",
            "target": "current",
        }

    def _open(self, action_xmlid):
        return self.env["ir.actions.act_window"]._for_xml_id(action_xmlid)

    def action_open_arrears(self):
        return self._open("mfi_loan.action_mfi_loan_arrears")

    def action_open_active(self):
        action = self._open("mfi_loan.action_mfi_loan")
        action["context"] = {"search_default_active": 1}
        return action

    def action_open_approvals(self):
        action = self._open("mfi_loan.action_mfi_loan")
        action["context"] = {"search_default_pending_approval": 1}
        return action

    def action_open_collections(self):
        return self._open("mfi_loan.action_mfi_collections_late")
