from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from . import rules
from .rules import APPROVAL_CHAIN, SA, TERMS, r2

STATES = [
    ("draft", "Draft"),
    ("pending_information", "Pending information"),
    ("pending_approval", "Pending approval"),
    ("approved", "Approved"),
    ("active", "Active"),
    ("repaid", "Repaid"),
    ("rejected", "Rejected"),
    ("written_off", "Written off"),
]
DISBURSED_STATES = ("active", "repaid", "written_off")
EDITABLE_STATES = ("draft", "pending_information")
# Changing these re-prices the loan.
PRICING_FIELDS = {"principal", "product_id", "partner_id", "term"}
# Documents each loan type needs before approval, besides the signed agreement.
LOAN_DOCUMENTS = {
    "logbook": ("ntsa_report", "valuation_report", "logbook"),
    "title_deed": ("title_deed", "valuation_report"),
    "chattels": ("chattels_agreement",),
}


class MfiLoan(models.Model):
    _name = "mfi.loan"
    _description = "Loan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char("Loan S/N", default="New", readonly=True, copy=False, index=True)
    state = fields.Selection(STATES, default="draft", required=True, readonly=True, tracking=True, copy=False)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")

    # The application
    partner_id = fields.Many2one(
        "res.partner", "Client", required=True, tracking=True, index=True,
        domain=[("is_mfi_client", "=", True)],
    )
    product_id = fields.Many2one("mfi.product", "Loan type", required=True, tracking=True)
    product_category = fields.Selection(related="product_id.category")
    principal = fields.Monetary(required=True, tracking=True)
    term = fields.Selection(
        [("two_weeks", "Two weeks (14 days)"), ("one_month", "One month (30 days)")],
        required=True, default="one_month", tracking=True,
    )

    # The terms, fixed when priced (before approval) and kept with the loan
    term_days = fields.Integer(readonly=True, copy=False)
    daily_rate = fields.Float(digits=(6, 4), readonly=True, copy=False)
    penalty_rate = fields.Float(digits=(6, 4), readonly=True, copy=False)
    min_interest_days = fields.Integer(readonly=True, copy=False)
    interest = fields.Monetary(readonly=True, copy=False)
    total_repayable = fields.Monetary(readonly=True, copy=False)
    installment = fields.Monetary("Daily instalment", readonly=True, copy=False)
    is_first_loan = fields.Boolean(readonly=True, copy=False)
    fee_line_ids = fields.One2many("mfi.loan.fee", "loan_id", "Fees", readonly=True, copy=False)
    upfront_total = fields.Monetary("Fees paid upfront", compute="_compute_fee_totals", store=True)
    deducted_total = fields.Monetary("Fees deducted", compute="_compute_fee_totals", store=True)
    net_disbursement = fields.Monetary(compute="_compute_fee_totals", store=True)

    # Guarantor and security
    guarantor_name = fields.Char(tracking=True)
    guarantor_id_number = fields.Char("Guarantor ID number")
    guarantor_phone = fields.Char()
    chattel_ids = fields.One2many("mfi.loan.chattel", "loan_id", "Chattels", copy=True)
    chattels_location = fields.Char("Home location of the assets")
    vehicle_reg_no = fields.Char("Registration number")
    vehicle_make = fields.Char("Make")
    vehicle_model = fields.Char("Model")
    vehicle_year = fields.Char("Year")
    title_no = fields.Char("Title number")
    land_location = fields.Char("Location")
    registered_owner = fields.Char()
    document_ids = fields.One2many("mfi.client.document", "loan_id", "Loan documents")

    # Checks before approval
    upfront_fee_ref = fields.Char("Upfront fee reference", tracking=True, copy=False)
    house_visit_date = fields.Date(copy=False)
    house_visit_officer = fields.Char(copy=False)
    house_visit_applicant_met = fields.Boolean("Applicant met", default=True, copy=False)
    house_visit_observations = fields.Text(copy=False)
    agreement_generated_at = fields.Datetime(readonly=True, copy=False)
    agreement_sent_at = fields.Datetime(readonly=True, copy=False)
    agreement_sent_via = fields.Selection(
        [("email", "Email"), ("whatsapp", "WhatsApp"), ("in_person", "In person")], copy=False,
    )
    client_documents_missing = fields.Char(related="partner_id.mfi_documents_missing")
    checklist_missing = fields.Char("Still outstanding", compute="_compute_checklist_missing")

    # Approvals
    approval_stage = fields.Integer(readonly=True, copy=False)
    approval_ids = fields.One2many("mfi.loan.approval", "loan_id", "Decisions", readonly=True, copy=False)
    rejection_reason = fields.Text(readonly=True, copy=False)
    submitted_at = fields.Datetime(readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    can_approve = fields.Boolean(compute="_compute_can_approve")
    awaiting_me = fields.Boolean(
        "Awaiting my decision", compute="_compute_can_approve", search="_search_awaiting_me"
    )

    # Disbursement
    disbursement_method = fields.Selection(
        [("mpesa", "M-Pesa"), ("bank", "Bank"), ("cash", "Cash")], readonly=True, copy=False
    )
    disbursement_ref = fields.Char("Disbursement reference", readonly=True, copy=False)
    disbursed_date = fields.Date(readonly=True, copy=False)
    disbursed_by = fields.Many2one("res.users", readonly=True, copy=False)
    start_date = fields.Date("First instalment due", readonly=True, copy=False)
    maturity_date = fields.Date(readonly=True, copy=False)

    # Repayment
    installment_ids = fields.One2many("mfi.loan.installment", "loan_id", "Schedule", readonly=True, copy=False)
    payment_ids = fields.One2many("mfi.payment", "loan_id", "Payments", readonly=True, copy=False)
    amount_paid = fields.Monetary("Paid to instalments", compute="_compute_balance", store=True)
    penalty_accrued = fields.Monetary("Default interest charged", readonly=True, copy=False)
    penalty_paid = fields.Monetary("Default interest paid", readonly=True, copy=False)
    penalty_through = fields.Date("Default interest charged to", readonly=True, copy=False)
    penalty_due = fields.Monetary("Default interest due", compute="_compute_balance", store=True)
    outstanding = fields.Monetary(compute="_compute_balance", store=True)
    health = fields.Selection(
        [("current", "Current"), ("arrears", "In arrears"), ("overdue", "Overdue")], readonly=True, copy=False,
        help="In arrears: instalments due before today are unpaid. Overdue: past maturity with a balance.",
    )
    days_past_due = fields.Integer("DPD", readonly=True, copy=False,
                                   help="Days since the oldest unpaid instalment fell due.")
    arrears_amount = fields.Monetary(readonly=True, copy=False)
    oldest_unpaid_due = fields.Date(readonly=True, copy=False)
    closed_date = fields.Date(readonly=True, copy=False)
    written_off_date = fields.Date(readonly=True, copy=False)
    write_off_reason = fields.Text(readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Computations
    # ------------------------------------------------------------------

    @api.depends("principal", "fee_line_ids.amount", "fee_line_ids.timing")
    def _compute_fee_totals(self):
        for loan in self:
            upfront = sum(loan.fee_line_ids.filtered(lambda f: f.timing == "upfront").mapped("amount"))
            deducted = sum(loan.fee_line_ids.filtered(lambda f: f.timing == "deducted").mapped("amount"))
            loan.upfront_total = r2(upfront)
            loan.deducted_total = r2(deducted)
            loan.net_disbursement = r2(loan.principal - deducted)

    @api.depends("state", "total_repayable", "installment_ids.amount_paid", "penalty_accrued", "penalty_paid")
    def _compute_balance(self):
        for loan in self:
            paid = r2(sum(loan.installment_ids.mapped("amount_paid")))
            penalty_due = r2(loan.penalty_accrued - loan.penalty_paid)
            loan.amount_paid = paid
            loan.penalty_due = penalty_due
            loan.outstanding = (
                r2(loan.total_repayable - paid + penalty_due) if loan.state == "active" else 0
            )

    @api.depends_context("uid")
    @api.depends("state", "approval_stage", "approval_ids")
    def _compute_can_approve(self):
        for loan in self:
            loan.can_approve = loan.awaiting_me = not loan._approval_problem()

    def _search_awaiting_me(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(self.env._("Unsupported search on Awaiting my decision"))
        user = self.env.user
        stages = [
            index + 1 for index, group in enumerate(APPROVAL_CHAIN)
            if user.has_group(group) or user.has_group(SA)
        ]
        domain = [("state", "=", "pending_approval"), ("approval_stage", "in", stages),
                  ("create_uid", "!=", user.id), ("approval_ids", "not any", [("user_id", "=", user.id)])]
        if (operator == "=") != value:
            domain = ["!", "&", "&", "&"] + domain
        return domain

    @api.depends("product_category", "document_ids.kind", "agreement_generated_at",
                 "house_visit_date", "house_visit_officer", "house_visit_observations")
    def _compute_checklist_missing(self):
        for loan in self:
            loan.checklist_missing = ", ".join(loan._checklist_problems())

    @api.constrains("principal", "product_id")
    def _check_principal(self):
        for loan in self:
            product = loan.product_id
            if product and not product.min_amount <= loan.principal <= product.max_amount:
                raise ValidationError(self.env._(
                    "Loan amount must be between KES %(min)s and KES %(max)s.",
                    min=f"{product.min_amount:,.0f}", max=f"{product.max_amount:,.0f}",
                ))

    @api.onchange("principal", "product_id", "term")
    def _onchange_quote(self):
        days = TERMS.get(self.term, 0)
        rate = self.product_id.daily_rate
        self.update({"term_days": days, "daily_rate": rate, **rules.quote(self.principal, rate, days)})

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def _reprice(self):
        """Fix the terms and fees from the loan type and fee table (only before approval)."""
        Fee = self.env["mfi.fee"].sudo()
        for loan in self.sudo():
            if loan.state not in EDITABLE_STATES:
                continue
            product = loan.product_id
            days = TERMS.get(loan.term, 0)
            first = not self.sudo().search_count([
                ("partner_id", "=", loan.partner_id.id),
                ("state", "in", DISBURSED_STATES),
                ("id", "!=", loan.id),
            ])
            lines = [(5, 0, 0)]
            for fee in Fee.search([]):
                if fee._applies(loan.principal, product.category, first):
                    timing = "upfront" if (first and fee.upfront_on_first_loan) else "deducted"
                    lines.append((0, 0, {
                        "fee_id": fee.id, "name": fee.name, "amount": fee.amount, "timing": timing,
                    }))
            loan.write({
                **rules.quote(loan.principal, product.daily_rate, days),
                "term_days": days,
                "daily_rate": product.daily_rate,
                "penalty_rate": product.penalty_rate,
                "min_interest_days": product.min_interest_days,
                "is_first_loan": first,
                "fee_line_ids": lines,
            })

    @api.model_create_multi
    def create(self, vals_list):
        rules.check(self.env, "loans.create")
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code("mfi.loan") or "New"
        loans = super().create(vals_list)
        loans._reprice()
        return loans

    def write(self, vals):
        if PRICING_FIELDS & vals.keys():
            for loan in self:
                if loan.state not in EDITABLE_STATES:
                    raise UserError(self.env._("%s can no longer be changed.", loan.name))
        result = super().write(vals)
        if PRICING_FIELDS & vals.keys():
            self._reprice()
        return result

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _application_problems(self):
        """What must be filled in before the application goes to the officer."""
        self.ensure_one()
        problems = []
        if not self.partner_id.mfi_documents_complete:
            problems.append(self.env._("Missing client documents: %s", self.partner_id.mfi_documents_missing))
        if not (self.guarantor_name and self.guarantor_id_number and self.guarantor_phone):
            problems.append(self.env._("Guarantor name, ID number and phone are required"))
        category = self.product_id.category
        if category == "chattels":
            if not self.chattel_ids or any(
                not (c.description or "").strip() or c.quantity <= 0 or c.value <= 0 for c in self.chattel_ids
            ):
                problems.append(self.env._("Fill in every chattel item (description, quantity and value)"))
            if not (self.chattels_location or "").strip():
                problems.append(self.env._("Enter the home location of the assets"))
        elif category == "logbook":
            if not (self.vehicle_reg_no and self.vehicle_make and self.vehicle_model and self.vehicle_year):
                problems.append(self.env._("Fill in the vehicle registration number, make, model and year"))
        elif category == "title_deed":
            if not (self.title_no and self.land_location and self.registered_owner):
                problems.append(self.env._("Fill in the title number, location and registered owner"))
        return problems

    def _checklist_problems(self):
        """The application's checklist: its documents, the agreement and the house visit."""
        self.ensure_one()
        kinds = set(self.document_ids.mapped("kind"))
        labels = dict(self.env["mfi.client.document"]._fields["kind"].selection)
        problems = [labels[k] for k in LOAN_DOCUMENTS.get(self.product_id.category, ()) if k not in kinds]
        if not self.agreement_generated_at:
            problems.append(self.env._("Loan agreement generated"))
        if "signed_agreement" not in kinds:
            problems.append(labels["signed_agreement"])
        if not (self.house_visit_date and self.house_visit_officer and self.house_visit_observations):
            problems.append(self.env._("House visit verification"))
        return problems

    def _approval_problem(self):
        """Why the current user cannot decide this loan's current stage, or False."""
        self.ensure_one()
        user = self.env.user
        if self.state != "pending_approval":
            return self.env._("This application is not awaiting approval.")
        if not 1 <= self.approval_stage <= len(APPROVAL_CHAIN):
            return self.env._("This application has no approval stage open.")
        group = APPROVAL_CHAIN[self.approval_stage - 1]
        if not (user.has_group(group) or user.has_group(SA)):
            return self.env._("This stage needs sign-off from: %s", self.env.ref(group).name)
        if self.create_uid == user:
            return self.env._("You cannot approve an application you created (maker-checker).")
        if user in self.approval_ids.user_id:
            return self.env._("You have already acted on this application at an earlier stage.")
        return False

    # ------------------------------------------------------------------
    # Application and approval
    # ------------------------------------------------------------------

    def action_submit(self):
        """Draft to Pending information."""
        rules.check(self.env, "loans.create")
        for loan in self:
            if loan.state != "draft":
                raise UserError(self.env._("Only draft applications can be sent to the officer."))
            if loan.partner_id.mfi_blacklisted:
                raise UserError(self.env._("%s is blacklisted.", loan.partner_id.name))
            problems = loan._application_problems()
            if problems:
                raise UserError(". ".join(problems))
            loan.state = "pending_information"
            loan.message_post(body=self.env._("Sent to the officer."))

    def action_generate_agreement(self):
        rules.check(self.env, "loans.create")
        for loan in self:
            if loan.state not in EDITABLE_STATES:
                raise UserError(self.env._("The agreement can only be generated before approval."))
            loan.agreement_generated_at = fields.Datetime.now()
        return self.env.ref("mfi_loan.action_report_mfi_loan_agreement").report_action(self)

    def action_mark_agreement_sent(self):
        """Placeholder until Odoo Sign: records how the agreement went out."""
        rules.check(self.env, "loans.create")
        for loan in self:
            if not loan.agreement_generated_at:
                raise UserError(self.env._("Generate the agreement first."))
            if not loan.agreement_sent_via:
                raise UserError(self.env._("Choose how the agreement was sent."))
            loan.agreement_sent_at = fields.Datetime.now()

    def action_send_for_approval(self):
        rules.check(self.env, "loans.create")
        for loan in self:
            if loan.state != "pending_information":
                raise UserError(self.env._("Only applications in Pending information can be sent for approval."))
            problems = []
            outstanding = loan._checklist_problems()
            if outstanding:
                problems.append(self.env._("Still outstanding: %s", ", ".join(outstanding)))
            if not loan.partner_id.mfi_documents_complete:
                problems.append(self.env._("Client documents are incomplete"))
            if loan.upfront_total > 0 and not (loan.upfront_fee_ref or "").strip():
                problems.append(self.env._(
                    "Record the payment reference for the upfront non-refundable fees (KES %s)",
                    f"{loan.upfront_total:,.0f}"))
            if problems:
                raise UserError(". ".join(problems))
            loan.write({
                "state": "pending_approval",
                "approval_stage": 1,
                "submitted_at": fields.Datetime.now(),
                "upfront_fee_ref": (loan.upfront_fee_ref or "").strip().upper() or False,
            })
            loan.message_post(body=self.env._("Sent for approval."))

    def _record_decision(self, decision, comment):
        self.ensure_one()
        self.env["mfi.loan.approval"].sudo().create({
            "loan_id": self.id, "stage": self.approval_stage, "decision": decision,
            "comment": comment, "user_id": self.env.user.id,
        })

    def action_approve(self, comment=""):
        for loan in self:
            problem = loan._approval_problem()
            if problem:
                raise UserError(problem)
            if not loan.partner_id.mfi_documents_complete:
                raise UserError(self.env._("Client documents incomplete: %s", loan.partner_id.mfi_documents_missing))
            loan._record_decision("approved", comment or "")
            if loan.approval_stage >= len(APPROVAL_CHAIN):
                loan.write({"state": "approved", "approved_at": fields.Datetime.now(),
                            "approval_stage": loan.approval_stage + 1})
                loan.message_post(body=self.env._("Approved at every stage."))
            else:
                loan.approval_stage += 1
                loan.message_post(body=self.env._("Stage %s approved.", loan.approval_stage - 1))

    def action_reject(self, reason):
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise UserError(self.env._("Give a reason for rejecting."))
        for loan in self:
            problem = loan._approval_problem()
            if problem:
                raise UserError(problem)
            loan._record_decision("rejected", reason)
            loan.write({"state": "rejected", "rejection_reason": reason})
            loan.message_post(body=self.env._("Rejected: %s", reason))

    def action_reopen(self):
        rules.check(self.env, "loans.create")
        for loan in self:
            if loan.state != "rejected":
                raise UserError(self.env._("Only rejected applications can be reopened."))
            loan.write({"state": "draft", "approval_stage": 0, "rejection_reason": False})
            loan._reprice()

    # ------------------------------------------------------------------
    # Disbursement
    # ------------------------------------------------------------------

    def action_disburse(self, method, reference, date=None):
        rules.check(self.env, "loans.disburse")
        reference = (reference or "").strip()
        if method not in ("mpesa", "bank", "cash"):
            raise UserError(self.env._("Choose a method."))
        if len(reference) < 3:
            raise UserError(self.env._("Enter the disbursement reference."))
        date = fields.Date.to_date(date) or fields.Date.context_today(self)
        user = self.env.user
        for loan in self:
            if loan.state != "approved":
                raise UserError(self.env._("Only approved loans can be disbursed."))
            if loan.create_uid == user and not user.has_group(SA):
                raise AccessError(self.env._("The creator of an application cannot disburse it."))
            start = date + timedelta(days=1)
            days, each, total = loan.term_days, loan.installment, loan.total_repayable
            schedule = [(5, 0, 0)] + [
                (0, 0, {
                    "seq": seq,
                    "due_date": start + timedelta(days=seq - 1),
                    "amount_due": max(each if seq < days else r2(total - each * (days - 1)), 0),
                })
                for seq in range(1, days + 1)
            ]
            loan.sudo().write({
                "state": "active",
                "disbursement_method": method,
                "disbursement_ref": reference,
                "disbursed_date": date,
                "disbursed_by": user.id,
                "start_date": start,
                "maturity_date": start + timedelta(days=days - 1),
                "penalty_through": date,
                "installment_ids": schedule,
            })
            loan.message_post(body=self.env._(
                "Disbursed KES %(net)s by %(method)s, reference %(ref)s.",
                net=f"{loan.net_disbursement:,.2f}", method=method, ref=reference))
        self._accrue_penalty()
        self._update_health()

    # ------------------------------------------------------------------
    # Default interest, payments and balances
    # ------------------------------------------------------------------

    def _accrue_penalty(self, today=None):
        """Charge default interest for each day since last charged: the rate on every
        instalment past its due date and still unpaid."""
        today = fields.Date.to_date(today) or fields.Date.context_today(self)
        for loan in self.sudo():
            if loan.state != "active" or not loan.penalty_through:
                continue
            days = (today - loan.penalty_through).days
            if days <= 0:
                continue
            unpaid = [(i.due_date, i.amount_due - i.amount_paid)
                      for i in loan.installment_ids if i.amount_due > i.amount_paid]
            charge = 0.0
            for offset in range(1, days + 1):
                day = loan.penalty_through + timedelta(days=offset)
                charge += sum(amount for due, amount in unpaid if due < day) * loan.penalty_rate
            loan.write({"penalty_accrued": r2(loan.penalty_accrued + charge), "penalty_through": today})

    def _allocate(self, amount, when):
        """Apply money to default interest first, then instalments in order.
        Returns (to default interest, to instalments, overpayment)."""
        self.ensure_one()
        loan = self.sudo()
        remaining = r2(amount)
        to_penalty = min(remaining, max(r2(loan.penalty_accrued - loan.penalty_paid), 0))
        remaining = r2(remaining - to_penalty)
        to_installments = 0.0
        for inst in loan.installment_ids.sorted("seq"):
            if remaining <= 0:
                break
            if inst.amount_paid >= inst.amount_due:
                continue
            part = min(remaining, r2(inst.amount_due - inst.amount_paid))
            paid = r2(inst.amount_paid + part)
            inst.write({"amount_paid": paid, "paid_date": when if paid >= inst.amount_due else False})
            remaining = r2(remaining - part)
            to_installments = r2(to_installments + part)
        loan.penalty_paid = r2(loan.penalty_paid + to_penalty)
        return to_penalty, to_installments, remaining

    def _close_if_repaid(self):
        for loan in self.sudo():
            open_installments = any(i.amount_paid < i.amount_due - 0.005 for i in loan.installment_ids)
            if loan.state == "active" and not open_installments and loan.penalty_accrued - loan.penalty_paid < 0.005:
                loan.write({"state": "repaid", "closed_date": fields.Date.context_today(self)})
                loan.message_post(body=self.env._("Repaid in full."))

    def _reallocate(self):
        """Re-apply every allocated payment from scratch, after a reversal."""
        for loan in self.sudo():
            loan.installment_ids.write({"amount_paid": 0, "paid_date": False})
            vals = {"penalty_paid": 0}
            if loan.state == "repaid":
                vals.update(state="active", closed_date=False)
            loan.write(vals)
            for payment in loan.payment_ids.filtered(lambda p: p.state == "allocated").sorted(lambda p: (p.date, p.id)):
                to_penalty, to_installments, over = loan._allocate(payment.amount, payment.date)
                payment.with_context(mfi_payment_internal=True).write({
                    "to_penalty": to_penalty, "to_installments": to_installments, "overpayment": over,
                })
            loan._close_if_repaid()
        self._update_health()

    def _update_health(self, today=None):
        today = fields.Date.to_date(today) or fields.Date.context_today(self)
        for loan in self.sudo():
            if loan.state != "active":
                vals = {"health": False, "days_past_due": 0, "arrears_amount": 0, "oldest_unpaid_due": False}
            else:
                past = loan.installment_ids.filtered(lambda i: i.due_date < today)
                arrears = r2(sum(past.mapped("amount_due")) - sum(past.mapped("amount_paid")))
                unpaid = [i.due_date for i in past if i.amount_paid < i.amount_due - 0.005]
                oldest = min(unpaid) if unpaid else False
                if loan.maturity_date and today > loan.maturity_date and loan.outstanding > 0.005:
                    health = "overdue"
                elif arrears > 0.005:
                    health = "arrears"
                else:
                    health = "current"
                vals = {
                    "health": health,
                    "days_past_due": max((today - oldest).days, 0) if oldest else 0,
                    "arrears_amount": arrears,
                    "oldest_unpaid_due": oldest,
                }
            if any(loan[k] != v for k, v in vals.items()):
                loan.write(vals)

    @api.model
    def _cron_daily(self):
        loans = self.search([("state", "=", "active")])
        loans._accrue_penalty()
        loans._update_health()

    def action_record_payment(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Record payment"),
            "res_model": "mfi.payment",
            "view_mode": "form",
            "target": "new",
            "context": {"default_loan_id": self.id},
        }

    # ------------------------------------------------------------------
    # Early settlement and write-off
    # ------------------------------------------------------------------

    def _settlement_quote(self, today=None):
        """What closes the loan today: interest for the days so far (at least the
        minimum, at most the term), less what is paid, plus default interest due."""
        self.ensure_one()
        today = fields.Date.to_date(today) or fields.Date.context_today(self)
        self._accrue_penalty(today)
        if self.state != "active":
            raise UserError(self.env._("Loan is not active."))
        days = max((today - self.start_date).days + 1, 0)
        interest_days = min(max(days, self.min_interest_days), self.term_days)
        interest = r2(self.principal * self.daily_rate * interest_days)
        new_total = r2(self.principal + interest)
        penalty_due = r2(self.penalty_accrued - self.penalty_paid)
        return {
            "interest_days": interest_days,
            "interest": interest,
            "new_total_payable": new_total,
            "penalty_due": penalty_due,
            "amount_paid": self.amount_paid,
            "settlement_amount": r2(max(new_total - self.amount_paid, 0) + penalty_due),
        }

    def action_settle(self, amount, method, reference=None, today=None):
        rules.check(self.env, "payments.record")
        self.ensure_one()
        today = fields.Date.to_date(today) or fields.Date.context_today(self)
        settlement = self._settlement_quote(today)
        if r2(amount) < settlement["settlement_amount"] - 0.005:
            raise UserError(self.env._(
                "Amount must be at least KES %s to settle early", f"{settlement['settlement_amount']:,.2f}"))
        loan = self.sudo()
        loan.installment_ids.filtered(
            lambda i: i.due_date > today and i.amount_paid == 0 and i.seq > 1
        ).unlink()
        remaining = loan.installment_ids.sorted("seq")
        if remaining:
            before_last = sum(remaining[:-1].mapped("amount_due"))
            last = remaining[-1]
            last.amount_due = max(r2(settlement["new_total_payable"] - before_last), last.amount_paid)
        loan.write({
            "interest": settlement["interest"],
            "total_repayable": settlement["new_total_payable"],
            "term_days": len(remaining),
            "maturity_date": remaining[-1].due_date if remaining else loan.maturity_date,
        })
        return self.env["mfi.payment"].create({
            "loan_id": self.id, "amount": amount, "method": method, "reference": reference,
            "date": today, "note": self.env._("Early settlement."),
        })

    def action_write_off(self, reason):
        rules.check(self.env, "loans.writeoff")
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise UserError(self.env._("Give a reason."))
        for loan in self:
            if loan.state != "active":
                raise UserError(self.env._("Only active loans can be written off."))
            loan._accrue_penalty()
            outstanding = loan.outstanding
            loan.sudo().write({
                "state": "written_off",
                "written_off_date": fields.Date.context_today(self),
                "write_off_reason": reason,
            })
            loan.message_post(body=self.env._(
                "Written off with KES %(amount)s outstanding: %(reason)s",
                amount=f"{outstanding:,.2f}", reason=reason))
        self._update_health()


class MfiLoanFee(models.Model):
    _name = "mfi.loan.fee"
    _description = "Fee on a loan"
    _order = "id"

    loan_id = fields.Many2one("mfi.loan", required=True, ondelete="cascade", index=True)
    fee_id = fields.Many2one("mfi.fee", ondelete="set null")
    name = fields.Char(required=True)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    amount = fields.Monetary(required=True)
    timing = fields.Selection([("upfront", "Paid upfront"), ("deducted", "Deducted from payout")], required=True)


class MfiLoanChattel(models.Model):
    _name = "mfi.loan.chattel"
    _description = "Chattel offered as security"
    _order = "id"

    loan_id = fields.Many2one("mfi.loan", required=True, ondelete="cascade", index=True)
    description = fields.Char(required=True)
    quantity = fields.Float(default=1)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    value = fields.Monetary()


class MfiLoanInstallment(models.Model):
    _name = "mfi.loan.installment"
    _description = "Daily instalment"
    _order = "loan_id, seq"

    loan_id = fields.Many2one("mfi.loan", required=True, ondelete="cascade", index=True)
    seq = fields.Integer("No.", required=True)
    due_date = fields.Date(required=True)
    currency_id = fields.Many2one(related="loan_id.currency_id")
    amount_due = fields.Monetary(required=True)
    amount_paid = fields.Monetary()
    paid_date = fields.Date()


class MfiLoanApproval(models.Model):
    _name = "mfi.loan.approval"
    _description = "Approval decision on a loan"
    _order = "id"

    loan_id = fields.Many2one("mfi.loan", required=True, ondelete="cascade", index=True)
    stage = fields.Integer(required=True)
    decision = fields.Selection([("approved", "Approved"), ("rejected", "Rejected")], required=True)
    comment = fields.Text()
    user_id = fields.Many2one("res.users", "Decided by", required=True)
    decided_at = fields.Datetime(default=fields.Datetime.now, required=True)
