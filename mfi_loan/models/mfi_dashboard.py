from collections import defaultdict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from .mfi_loan import BUCKETS, HEALTH
from .rules import r2

# Every figure comes from Accounting (DECISIONS D-017): money in is the loans'
# receivable credited in a bank, cash or M-Pesa journal (payments and statement
# lines alike); money due is the loan invoices' instalments.
COLLECTED = [("account_id.account_type", "=", "asset_receivable"), ("parent_state", "=", "posted"),
             ("credit", ">", 0), ("journal_id.type", "in", ("bank", "cash")),
             ("partner_id.is_mfi_client", "=", True), ("move_id.mfi_kind", "!=", "fee")]
DUE = [("account_id.account_type", "=", "asset_receivable"), ("parent_state", "=", "posted"),
       ("move_id.mfi_kind", "=", "loan"), ("debit", ">", 0)]
# Period picker on the dashboard: key -> label
PERIODS = [("today", "Today"), ("7d", "7 days"), ("30d", "30 days"), ("month", "This month"), ("year", "This year")]


def _trend(now, before):
    """Change against the previous period, in %, or None when there is nothing to compare."""
    if not before:
        return None
    return r2((now - before) / abs(before) * 100)


class MfiDashboard(models.TransientModel):
    """The portfolio snapshot. The live dashboard (client action mfi_loan.dashboard)
    reads everything through mfi_dashboard_data(); the fields stay for reports and tests."""

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
    due_today = fields.Monetary(compute="_compute_all")
    disbursed_month = fields.Monetary("Disbursed this month", compute="_compute_all")
    pending_information = fields.Integer(compute="_compute_all")
    pending_approval = fields.Integer(compute="_compute_all")
    to_disburse = fields.Integer(compute="_compute_all")
    clients = fields.Integer(compute="_compute_all")
    collection_rate_30 = fields.Float("30-day collection rate (%)", compute="_compute_all")

    @api.depends("as_of")
    def _compute_all(self):
        for board in self:
            today = board.as_of or fields.Date.context_today(self)
            snap = self._mfi_snapshot()
            board.update({
                "active_count": snap["active"]["count"],
                "active_outstanding": snap["active"]["amount"],
                "arrears_count": snap["arrears"]["count"],
                "arrears_missed": snap["arrears"]["amount"],
                "overdue_count": snap["overdue"]["count"],
                "overdue_outstanding": snap["overdue"]["amount"],
                "par_1": snap["par"]["1"], "par_7": snap["par"]["7"], "par_30": snap["par"]["30"],
                "collected_today": self._mfi_collected(today, today),
                "due_today": self._mfi_due(today, today),
                "disbursed_month": self._mfi_disbursed(today.replace(day=1), today)[0],
                "pending_information": snap["pipeline"]["pending_information"],
                "pending_approval": snap["pipeline"]["pending_approval"],
                "to_disburse": snap["pipeline"]["approved"],
                "clients": self.env["res.partner"].search_count([("is_mfi_client", "=", True)]),
                "collection_rate_30": self._mfi_rate(today - timedelta(days=29), today),
            })

    # ------------------------------------------------------------------
    # Building blocks
    # ------------------------------------------------------------------

    def _mfi_collected(self, start, end):
        groups = self.env["account.move.line"].sudo()._read_group(
            COLLECTED + [("date", ">=", start), ("date", "<=", end)], [], ["credit:sum"])
        return groups[0][0] or 0.0

    def _mfi_due(self, start, end):
        groups = self.env["account.move.line"].sudo()._read_group(
            DUE + [("date_maturity", ">=", start), ("date_maturity", "<=", end)], [], ["debit:sum"])
        return groups[0][0] or 0.0

    def _mfi_rate(self, start, end):
        due = self._mfi_due(start, end)
        return r2(self._mfi_collected(start, end) / due * 100) if due else 0.0

    def _mfi_disbursed(self, start, end):
        groups = self.env["mfi.loan"]._read_group(
            [("disbursed_date", ">=", start), ("disbursed_date", "<=", end)], [], ["principal:sum", "__count"])
        return groups[0][0] or 0.0, groups[0][1]

    def _mfi_count(self, model, domain, start, end):
        return self.env[model].search_count(domain + [
            ("create_date", ">=", fields.Datetime.to_datetime(start)),
            ("create_date", "<", fields.Datetime.to_datetime(end + timedelta(days=1)))])

    def _mfi_snapshot(self):
        """Figures that do not depend on the period: the book as it stands."""
        Loan = self.env["mfi.loan"]
        active = Loan.search([("state", "=", "active")])
        total = sum(active.mapped("outstanding"))

        def par(days):
            at_risk = sum(active.filtered(lambda l: l.days_past_due >= days).mapped("outstanding"))
            return r2(at_risk / total * 100) if total else 0.0

        by_health = {key: active.filtered(lambda l, k=key: l.health == k) for key, _label in HEALTH}
        return {
            "active": {"count": len(active), "amount": total},
            "arrears": {"count": len(by_health["arrears"]),
                        "amount": sum(by_health["arrears"].mapped("arrears_amount"))},
            "overdue": {"count": len(by_health["overdue"]),
                        "amount": sum(by_health["overdue"].mapped("outstanding"))},
            "par": {"1": par(1), "7": par(7), "30": par(30)},
            "health": [{"key": key, "label": self.env._(label), "count": len(by_health[key]),
                        "amount": sum(by_health[key].mapped("outstanding"))} for key, label in HEALTH],
            "ageing": [{"key": key, "label": self.env._(label), "count": len(group),
                        "amount": sum(group.mapped("outstanding"))}
                       for key, label in BUCKETS
                       for group in [active.filtered(lambda l, k=key: l.ageing_bucket == k)]],
            "pipeline": {state: Loan.search_count([("state", "=", state)])
                         for state in ("pending_information", "pending_approval", "approved")},
            "late": by_health["arrears"] | by_health["overdue"],
        }

    @api.model
    def _mfi_period(self, period, today):
        """(start, end, previous start, previous end) for a period key."""
        start = {
            "today": today,
            "7d": today - timedelta(days=6),
            "month": today.replace(day=1),
            "year": today.replace(month=1, day=1),
        }.get(period, today - timedelta(days=29))
        days = (today - start).days + 1
        prev_end = start - timedelta(days=1)
        return start, today, prev_end - timedelta(days=days - 1), prev_end

    def _mfi_series(self, start, end):
        """Collected, due and disbursed per day (or per month over long periods)."""
        start = min(start, end - timedelta(days=6))  # at least a week, so "today" still shows a trend
        monthly = (end - start).days > 62
        grain = "month" if monthly else "day"
        buckets, cursor = [], start.replace(day=1) if monthly else start
        while cursor <= end:
            buckets.append(cursor)
            cursor += relativedelta(months=1) if monthly else timedelta(days=1)

        def grouped(model, domain, date_field, measure):
            totals = defaultdict(float)
            for when, amount in self.env[model].sudo()._read_group(
                    domain + [(date_field, ">=", buckets[0]), (date_field, "<=", end)],
                    [f"{date_field}:{grain}"], [f"{measure}:sum"]):
                if when:
                    totals[when] += amount or 0.0
            return [r2(totals.get(b, 0.0)) for b in buckets]

        label = "%b %Y" if monthly else "%d %b"
        return {
            "labels": [b.strftime(label) for b in buckets],
            "collected": grouped("account.move.line", COLLECTED, "date", "credit"),
            "due": grouped("account.move.line", DUE, "date_maturity", "debit"),
            "disbursed": grouped("mfi.loan", [], "disbursed_date", "principal"),
        }

    # ------------------------------------------------------------------
    # Live dashboard
    # ------------------------------------------------------------------

    @api.model
    def mfi_dashboard_data(self, period="30d"):
        """Everything the live dashboard shows, in one call."""
        today = fields.Date.context_today(self)
        start, end, prev_start, prev_end = self._mfi_period(period, today)
        snap = self._mfi_snapshot()
        Loan = self.env["mfi.loan"]
        series = self._mfi_series(start, end)

        def kpi(now, before, **extra):
            return {"value": now, "previous": before, "trend": _trend(now, before), **extra}

        disbursed, disbursed_count = self._mfi_disbursed(start, end)
        disbursed_before, _count = self._mfi_disbursed(prev_start, prev_end)
        client_domain = [("is_mfi_client", "=", True)]
        company = self.env.company
        currency = company.currency_id
        return {
            "user": self.env.user.name,
            "company": company.name,
            "today": fields.Date.to_string(today),
            "period": period,
            "periods": [{"key": key, "label": self.env._(label)} for key, label in PERIODS],
            "currency": {"symbol": currency.symbol or currency.name, "position": currency.position,
                         "name": currency.name},
            "kpis": {
                "collected": kpi(self._mfi_collected(start, end), self._mfi_collected(prev_start, prev_end),
                                 spark=series["collected"]),
                "disbursed": kpi(disbursed, disbursed_before, count=disbursed_count, spark=series["disbursed"]),
                "rate": kpi(self._mfi_rate(start, end), self._mfi_rate(prev_start, prev_end),
                            due=self._mfi_due(start, end)),
                "clients": kpi(self._mfi_count("res.partner", client_domain, start, end),
                               self._mfi_count("res.partner", client_domain, prev_start, prev_end),
                               total=self.env["res.partner"].search_count(client_domain)),
                "applications": kpi(self._mfi_count("mfi.loan", [], start, end),
                                    self._mfi_count("mfi.loan", [], prev_start, prev_end)),
            },
            "book": {key: snap[key] for key in ("active", "arrears", "overdue", "par")},
            "health": snap["health"],
            "ageing": snap["ageing"],
            "pipeline": dict(snap["pipeline"], mine=Loan.search_count([("awaiting_me", "=", True)])),
            "series": series,
            "late": [{
                "id": loan.id, "name": loan.name, "client": loan.partner_id.name,
                "days": loan.days_past_due, "amount": loan.outstanding, "health": loan.health,
            } for loan in snap["late"].sorted("days_past_due", reverse=True)[:6]],
            "approvals": [{
                "id": loan.id, "name": loan.name, "client": loan.partner_id.name, "amount": loan.principal,
                "stage": loan.approval_stage, "mine": loan.awaiting_me,
                "days": (today - loan.submitted_at.date()).days if loan.submitted_at else 0,
            } for loan in Loan.search([("state", "=", "pending_approval")],
                                      order="submitted_at asc, id asc", limit=6)],
            "payments": [{
                "id": pay.id, "client": pay.partner_id.name or self.env._("Unmatched"),
                "amount": pay.amount, "date": fields.Date.to_string(pay.date),
                "method": pay.journal_id.name, "matched": pay.is_reconciled,
            } for pay in self.env["account.payment"].sudo().search(
                [("payment_type", "=", "inbound"), ("state", "in", ("paid", "reconciled")),
                 "|", ("partner_id", "=", False), ("partner_id.is_mfi_client", "=", True)],
                order="date desc, id desc", limit=6)],
        }

    @api.model
    def mfi_dashboard_action(self, key, period="30d", value=None):
        """The list behind a card, chart segment or pipeline step."""
        today = fields.Date.context_today(self)
        start, end, _ps, _pe = self._mfi_period(period, today)

        def act(xmlid, name=None, domain=None, context=None):
            action = self.env["ir.actions.act_window"]._for_xml_id(xmlid)
            if name:
                action["name"] = name
            if domain is not None:
                action["domain"] = domain
            action["context"] = context or {}
            return action

        _ = self.env._
        loans = "mfi_loan.action_mfi_loan"
        span = [(">=", fields.Date.to_string(start)), ("<=", fields.Date.to_string(end))]
        created = [("create_date", ">=", fields.Datetime.to_string(fields.Datetime.to_datetime(start))),
                   ("create_date", "<", fields.Datetime.to_string(
                       fields.Datetime.to_datetime(end + timedelta(days=1))))]
        if key == "collected":
            return act("mfi_loan.action_mfi_payment", _("Collected"),
                       [("payment_type", "=", "inbound"), ("state", "in", ("paid", "reconciled"))]
                       + [("date", op, d) for op, d in span])
        if key == "disbursed":
            return act(loans, _("Disbursed"), [("disbursed_date", op, d) for op, d in span])
        if key == "rate":
            return act("mfi_loan.action_mfi_collections_late")
        if key == "clients":
            return act("mfi_loan.action_mfi_client", _("New clients"), [("is_mfi_client", "=", True)] + created)
        if key == "applications":
            return act(loans, _("New applications"), created)
        if key in ("active", "arrears", "overdue", "pending_information", "pending_approval", "approved",
                   "draft", "repaid", "rejected", "written_off"):
            return act(loans, context={f"search_default_{key}": 1})
        if key == "health" and value in dict(HEALTH):
            return act(loans, context={f"search_default_{'current' if value == 'current' else value}": 1})
        if key == "ageing" and value in dict(BUCKETS):
            return act(loans, _("Ageing: %s", dict(BUCKETS)[value]),
                       [("state", "=", "active"), ("ageing_bucket", "=", value)])
        if key == "mine":
            return act("mfi_loan.action_mfi_loan_my_tasks")
        if key == "late":
            return act("mfi_loan.action_mfi_collections_late")
        if key == "payments":
            return act("mfi_loan.action_mfi_payment")
        return act(loans)

    # ------------------------------------------------------------------
    # How it works: the presentation page (client action mfi_loan.how_it_works)
    # ------------------------------------------------------------------

    @api.model
    def mfi_how_it_works_data(self):
        """What the How it works page shows, read live so it matches this database:
        loans in each state, the loan types and the fee table."""
        from .mfi_loan import STATES
        from .mfi_product import CATEGORIES

        Loan = self.env["mfi.loan"]
        counts = {state: count for state, count in Loan._read_group([], ["state"], ["__count"])}
        categories = dict(CATEGORIES)
        company = self.env.company
        products = [{
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "category_label": categories.get(p.category, ""),
            "rate": p.daily_rate,
            "penalty": p.penalty_rate,
            "min_days": p.min_interest_days,
            "min": p.min_amount,
            "max": p.max_amount,
        } for p in self.env["mfi.product"].search([])]
        fees = [{
            "id": f.id,
            "name": f.name,
            "code": f.code,
            "amount": f.amount,
            "min": f.min_principal,
            "max": f.max_principal,
            "category": f.product_category or False,
            "first_only": f.first_loan_only,
            "upfront_first": f.upfront_on_first_loan and company.mfi_first_loan_fees_upfront,
        } for f in self.env["mfi.fee"].search([])]
        sample = Loan.search([("state", "=", "active")], limit=1, order="days_past_due desc, id desc")             or Loan.search([], limit=1, order="id desc")
        return {
            "company": company.name,
            "currency": company.currency_id.symbol or company.currency_id.name,
            "states": [{"key": k, "label": label, "count": counts.get(k, 0)} for k, label in STATES],
            "clients": self.env["res.partner"].search_count([("is_mfi_client", "=", True)]),
            "products": products,
            "fees": fees,
            "sample": {"id": sample.id, "name": sample.name, "client": sample.partner_id.name} if sample else False,
        }
