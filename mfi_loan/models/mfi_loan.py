from datetime import timedelta

from odoo import Command, api, fields, models
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
# One definition, used by the loan, the dashboard and the views.
HEALTH = [("current", "On time"), ("arrears", "In arrears"), ("overdue", "Overdue")]
BUCKETS = [("current", "Current"), ("1_7", "1-7 days"), ("8_14", "8-14 days"),
           ("15_30", "15-30 days"), ("30_plus", "30+ days")]
METHODS = [("mpesa", "M-Pesa"), ("bank", "Bank"), ("cash", "Cash")]
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
    total_charges = fields.Monetary("Charges", compute="_compute_fee_totals", store=True)
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
    disbursement_method = fields.Selection(METHODS, readonly=True, copy=False)
    disbursement_ref = fields.Char("Disbursement reference", readonly=True, copy=False)
    disbursed_date = fields.Date(readonly=True, copy=False)
    disbursed_by = fields.Many2one("res.users", readonly=True, copy=False)
    start_date = fields.Date("First instalment due", readonly=True, copy=False)
    maturity_date = fields.Date(readonly=True, copy=False)

    # Accounting (DECISIONS D-017): the loan's journal entries, and what is read from them
    move_ids = fields.One2many("account.move", "mfi_loan_id", "Journal entries", readonly=True, copy=False)
    invoice_id = fields.Many2one("account.move", "Loan invoice", readonly=True, copy=False)
    payment_ids = fields.One2many("account.payment", "mfi_loan_id", "Payments", readonly=True, copy=False)
    instalment_line_ids = fields.Many2many("account.move.line", string="Instalments",
                                           compute="_compute_instalment_lines")
    amount_paid = fields.Monetary("Paid to instalments", compute="_compute_balance", store=True)
    penalty_accrued = fields.Monetary("Default interest charged", compute="_compute_balance", store=True)
    penalty_paid = fields.Monetary("Default interest paid", compute="_compute_balance", store=True)
    penalty_through = fields.Date("Default interest charged to", readonly=True, copy=False)
    penalty_due = fields.Monetary("Default interest due", compute="_compute_balance", store=True)
    outstanding = fields.Monetary(compute="_compute_balance", store=True)
    health = fields.Selection(
        HEALTH, compute="_compute_balance", store=True,
        help="In arrears: instalments due before today are unpaid. Overdue: past maturity with a balance.",
    )
    days_past_due = fields.Integer("DPD", compute="_compute_balance", store=True,
                                   help="Days since the oldest unpaid instalment fell due.")
    arrears_amount = fields.Monetary(compute="_compute_balance", store=True)
    oldest_unpaid_due = fields.Date(compute="_compute_balance", store=True)
    ageing_bucket = fields.Selection(BUCKETS, "Bucket", compute="_compute_balance", store=True)
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
            loan.total_charges = r2(upfront + deducted)
            loan.net_disbursement = r2(loan.principal - deducted)

    def _receivable_lines(self, kinds=("loan", "penalty")):
        """The loan's posted receivable lines of these kinds (sudo: figures for everyone)."""
        self.ensure_one()
        return self.sudo().move_ids.line_ids.filtered(
            lambda l: l.parent_state == "posted" and l.account_id.account_type == "asset_receivable"
            and l.move_id.mfi_kind in kinds and l.balance > 0)

    @api.depends("move_ids.line_ids.amount_residual")
    def _compute_instalment_lines(self):
        for loan in self:
            loan.instalment_line_ids = loan._receivable_lines(("loan",)).sorted("date_maturity") if loan.id else False

    @api.depends("state", "maturity_date", "move_ids.state", "move_ids.line_ids.amount_residual")
    def _compute_balance(self):
        today = fields.Date.context_today(self)
        for loan in self:
            lines = loan._receivable_lines() if loan.id else self.env["account.move.line"]
            instalments = lines.filtered(lambda l: l.move_id.mfi_kind == "loan")
            penalties = lines - instalments

            def paid(lines_):
                # Money received: what is matched by anything but a rebate or a write-off.
                return sum(p.amount for line in lines_ for p in line.matched_credit_ids
                           if p.credit_move_id.move_id.mfi_kind not in ("settlement", "write_off"))

            loan.amount_paid = r2(paid(instalments))
            loan.penalty_accrued = r2(sum(penalties.mapped("balance")))
            loan.penalty_paid = r2(paid(penalties))
            loan.penalty_due = r2(sum(penalties.mapped("amount_residual")))
            if loan.state != "active":
                loan.update({"outstanding": 0, "health": False, "days_past_due": 0, "arrears_amount": 0,
                             "oldest_unpaid_due": False, "ageing_bucket": False})
                continue
            outstanding = r2(sum(lines.mapped("amount_residual")))
            late = instalments.filtered(lambda l: l.date_maturity and l.date_maturity < today)
            arrears = r2(sum(late.mapped("amount_residual")))
            unpaid = [l.date_maturity for l in late if l.amount_residual > 0.005]
            oldest = min(unpaid) if unpaid else False
            if loan.maturity_date and today > loan.maturity_date and outstanding > 0.005:
                health = "overdue"
            elif arrears > 0.005:
                health = "arrears"
            else:
                health = "current"
            dpd = max((today - oldest).days, 0) if oldest else 0
            loan.update({
                "outstanding": outstanding,
                "health": health,
                "days_past_due": dpd,
                "arrears_amount": arrears,
                "oldest_unpaid_due": oldest,
                "ageing_bucket": (
                    "current" if health == "current" else
                    "1_7" if dpd <= 7 else "8_14" if dpd <= 14 else "15_30" if dpd <= 30 else "30_plus"),
            })

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
                    upfront = first and fee.upfront_on_first_loan and loan.company_id.mfi_first_loan_fees_upfront
                    timing = "upfront" if upfront else "deducted"
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
        rules.audit(self.env, "loan.created", loans)
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
            rules.audit(self.env, "loan.sent_to_officer", loan)

    def action_generate_agreement(self):
        rules.check(self.env, "loans.create")
        for loan in self:
            if loan.state not in EDITABLE_STATES:
                raise UserError(self.env._("The agreement can only be generated before approval."))
            loan.agreement_generated_at = fields.Datetime.now()
            rules.audit(self.env, "loan.agreement_generated", loan)
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
            rules.audit(self.env, "loan.agreement_sent", loan, {"via": loan.agreement_sent_via})

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
            rules.audit(self.env, "loan.submitted", loan)

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
            rules.audit(self.env, "loan.approved", loan, {"stage": loan.approval_stage, "comment": comment})
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
            rules.audit(self.env, "loan.rejected", loan, {"stage": loan.approval_stage, "reason": reason})
            loan.write({"state": "rejected", "rejection_reason": reason})
            loan.message_post(body=self.env._("Rejected: %s", reason))

    def action_reopen(self):
        rules.check(self.env, "loans.create")
        for loan in self:
            if loan.state != "rejected":
                raise UserError(self.env._("Only rejected applications can be reopened."))
            loan.write({"state": "draft", "approval_stage": 0, "rejection_reason": False})
            loan._reprice()
            rules.audit(self.env, "loan.reopened", loan)

    # ------------------------------------------------------------------
    # Disbursement
    # ------------------------------------------------------------------

    def action_disburse(self, method, reference, date=None):
        rules.check(self.env, "loans.disburse")
        reference = (reference or "").strip()
        if method not in dict(METHODS):
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
            loan.sudo()._mfi_post_loan(method, reference, date)
            loan.message_post(body=self.env._(
                "Disbursed KES %(net)s by %(method)s, reference %(ref)s.",
                net=f"{loan.net_disbursement:,.2f}", method=method, ref=reference))
            rules.audit(self.env, "loan.disbursed", loan, {
                "method": method, "reference": reference, "date": date, "net": loan.net_disbursement})
        # A payout recorded late: default interest for the days already past (unless a
        # replay of history charges it day by day itself, as the sample data does).
        if not self.env.context.get("mfi_skip_accrual"):
            self._accrue_penalty()
        self._mfi_refresh()

    def _mfi_post_loan(self, method, reference, date):
        """Book the loan in Accounting: its invoice (principal and interest, a daily
        payment term: Odoo makes the instalments), the payout, and deducted fees.

        The one place a loan is posted: the local workflow calls it today; a sync
        from the lending service will call it with the loans it fetches (D-020)."""
        self.ensure_one()
        accounting = self.company_id._mfi_accounting()
        principal_product, interest_product = self.product_id._mfi_products()
        Move = self.env["account.move"].sudo()
        self.write({
            "state": "active",
            "disbursement_method": method,
            "disbursement_ref": reference,
            "disbursed_date": date,
            "disbursed_by": self.env.uid,
            "start_date": date + timedelta(days=1),
            "maturity_date": date + timedelta(days=self.term_days),
            "penalty_through": date,
        })
        invoice = Move.create({
            "move_type": "out_invoice",
            "partner_id": self.partner_id.id,
            "journal_id": accounting.loan_journal.id,
            "invoice_date": date,
            "date": date,
            "invoice_payment_term_id": self.env["account.payment.term"]._mfi_daily(
                self.term_days, self.company_id).id,
            "payment_reference": self.name,
            "ref": self.name,
            "mfi_loan_id": self.id,
            "mfi_kind": "loan",
            "invoice_line_ids": [
                Command.create({
                    "product_id": principal_product.id, "name": self.env._("Principal"),
                    "quantity": 1, "price_unit": self.principal,
                    "account_id": accounting.principal.id, "tax_ids": [Command.clear()],
                }),
                Command.create({
                    "product_id": interest_product.id,
                    "name": self.env._("Interest: %(days)s days at %(rate)s%% a day",
                                       days=self.term_days, rate=f"{self.daily_rate * 100:g}"),
                    "quantity": 1, "price_unit": self.interest,
                    "account_id": accounting.interest.id, "tax_ids": [Command.clear()],
                }),
            ],
        })
        invoice.action_post()
        self.invoice_id = invoice
        payout = self.env["account.payment"].sudo().create({
            "payment_type": "outbound",
            "partner_type": "customer",
            "partner_id": self.partner_id.id,
            "amount": self.net_disbursement,
            "journal_id": accounting.journals[method].id,
            "date": date,
            "memo": f"{self.name} {reference}",
            "destination_account_id": accounting.principal.id,
            "mfi_loan_id": self.id,
        })
        payout.action_post()
        payout.move_id.write({"mfi_loan_id": self.id, "mfi_kind": "disbursement"})
        deducted = self.fee_line_ids.filtered(lambda f: f.timing == "deducted" and f.amount)
        if deducted:
            fee_lines = [Command.create({
                "account_id": accounting.principal.id, "partner_id": self.partner_id.id,
                "name": self.env._("Fees deducted from the payout"), "debit": sum(deducted.mapped("amount")),
            })]
            for fee in deducted:
                product = fee.fee_id._mfi_product() if fee.fee_id else False
                fee_lines.append(Command.create({
                    "account_id": (product and product.property_account_income_id or accounting.fee).id,
                    "product_id": product and product.id,
                    "partner_id": self.partner_id.id, "name": fee.name, "credit": fee.amount,
                }))
            Move.create({
                "move_type": "entry", "journal_id": accounting.loan_journal.id, "date": date,
                "ref": self.env._("%s: fees deducted", self.name),
                "mfi_loan_id": self.id, "mfi_kind": "disbursement", "line_ids": fee_lines,
            }).action_post()
        self._mfi_post_upfront_fees(date)
        # The principal account clears: the invoice's principal against the payout and the fees.
        self.move_ids.line_ids.filtered(
            lambda l: l.account_id == accounting.principal and not l.reconciled and l.parent_state == "posted"
        ).reconcile()

    def _mfi_post_upfront_fees(self, date):
        """Fees paid before approval (with their reference): an invoice of the fee
        products, paid by that reference. Not part of the loan's balance."""
        upfront = self.fee_line_ids.filtered(lambda f: f.timing == "upfront" and f.amount)
        if not upfront:
            return
        accounting = self.company_id._mfi_accounting()
        invoice = self.env["account.move"].sudo().create({
            "move_type": "out_invoice", "partner_id": self.partner_id.id,
            "journal_id": accounting.loan_journal.id, "invoice_date": date, "date": date,
            "ref": self.name, "payment_reference": self.upfront_fee_ref or self.name,
            "mfi_loan_id": self.id, "mfi_kind": "fee",
            "invoice_line_ids": [Command.create({
                "product_id": fee.fee_id._mfi_product().id if fee.fee_id else False,
                "name": fee.name, "quantity": 1, "price_unit": fee.amount,
                "account_id": (fee.fee_id._mfi_product().property_account_income_id
                               if fee.fee_id else accounting.fee).id,
                "tax_ids": [Command.clear()],
            }) for fee in upfront],
        })
        invoice.action_post()
        payment = self.env["account.payment"].sudo().create({
            "payment_type": "inbound", "partner_type": "customer", "partner_id": self.partner_id.id,
            "amount": invoice.amount_total, "journal_id": accounting.journals["mpesa"].id, "date": date,
            "memo": self.upfront_fee_ref or self.env._("%s upfront fees", self.name), "mfi_loan_id": self.id,
        })
        payment.action_post()
        payment.move_id.write({"mfi_loan_id": self.id, "mfi_kind": "fee"})  # not a repayment
        (payment.move_id.line_ids | invoice.line_ids).filtered(
            lambda l: l.account_id.account_type == "asset_receivable").reconcile()

    # ------------------------------------------------------------------
    # Repayments: payments reconciled with the instalments, oldest first
    # ------------------------------------------------------------------

    def _mfi_register_payment(self, amount, method, reference=None, date=None, note=None):
        """Receive money for this loan: a posted payment, applied to the oldest
        instalment or charge first. The one place a repayment is booked (D-020)."""
        self.ensure_one()
        reference = (reference or "").strip().upper() or False
        if method not in dict(METHODS):
            raise UserError(self.env._("Choose a method."))
        if amount <= 0:
            raise UserError(self.env._("The amount must be positive."))
        if method != "cash" and not reference:
            raise UserError(self.env._("Enter the M-Pesa or bank reference."))
        accounting = self.company_id._mfi_accounting()
        journal = accounting.journals[method]
        Payment = self.env["account.payment"].sudo()
        if reference and Payment.search_count([("memo", "=", reference), ("journal_id", "=", journal.id),
                                                ("state", "!=", "canceled")]):
            raise UserError(self.env._("Reference %s has already been recorded.", reference))
        payment = Payment.create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.partner_id.id,
            "amount": amount,
            "journal_id": journal.id,
            "date": fields.Date.to_date(date) or fields.Date.context_today(self),
            "memo": reference or note or self.name,
            "payment_reference": self.name,
            "mfi_loan_id": self.id,
        })
        payment.action_post()
        self._mfi_apply(payment)
        return payment

    def _mfi_apply(self, payment):
        """Reconcile a payment with the loan's open lines, oldest due first."""
        self.ensure_one()
        credit = payment.sudo().move_id.line_ids.filtered(
            lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled)
        for line in self._receivable_lines().filtered(lambda l: not l.reconciled).sorted(
                lambda l: (l.date_maturity or l.date, l.id)):
            if credit.reconciled:
                break
            (credit | line).reconcile()

    def _mfi_follow_receivable(self):
        """After any reconciliation: repaid when nothing is left, active again if a
        payment was undone."""
        for loan in self.sudo():
            if loan.state == "active" and loan.outstanding <= 0.005 and loan.invoice_id:
                dates = [p.credit_move_id.date for line in loan._receivable_lines() for p in line.matched_credit_ids
                         if p.credit_move_id.move_id.mfi_kind not in ("settlement", "write_off")]
                loan.write({"state": "repaid", "closed_date": max(dates) if dates else fields.Date.context_today(self)})
                loan.message_post(body=self.env._("Repaid in full."))
            elif loan.state == "repaid":
                open_lines = loan._receivable_lines().filtered(lambda l: l.amount_residual > 0.005)
                if open_lines:
                    loan.write({"state": "active", "closed_date": False})
                    loan.message_post(body=self.env._("Reopened: a payment was undone."))

    def action_record_payment(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Record payment"),
            "res_model": "mfi.loan.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_loan_id": self.id},
        }

    def action_open_entries(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Journal entries of %s", self.name),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("mfi_loan_id", "=", self.id)],
            "context": {"create": False},
        }

    # ------------------------------------------------------------------
    # Default interest
    # ------------------------------------------------------------------

    def _accrue_penalty(self, today=None):
        """Charge default interest for each day since last charged: the rate on every
        instalment past its due date and still unpaid. Posted as one invoice."""
        today = fields.Date.to_date(today) or fields.Date.context_today(self)
        for loan in self.sudo():
            if loan.state != "active" or not loan.penalty_through:
                continue
            days = (today - loan.penalty_through).days
            if days <= 0:
                continue
            unpaid = [(l.date_maturity, l.amount_residual) for l in loan._receivable_lines(("loan",))
                      if l.amount_residual > 0.005]
            charge = 0.0
            for offset in range(1, days + 1):
                day = loan.penalty_through + timedelta(days=offset)
                charge += sum(amount for due, amount in unpaid if due < day) * loan.penalty_rate
            charge = r2(charge)
            if charge > 0:
                loan._mfi_post_charge("penalty", charge, today, self.env._(
                    "Default interest to %s", fields.Date.to_string(today)))
            loan.penalty_through = today

    def _mfi_post_charge(self, kind, amount, date, label, refund=False, account=None, product=None):
        """A posted invoice (or credit note) on the loan: default interest, a
        settlement rebate or a write-off. Credit notes are applied at once."""
        self.ensure_one()
        accounting = self.company_id._mfi_accounting()
        product = product or accounting.penalty_product
        move = self.env["account.move"].sudo().create({
            "move_type": "out_refund" if refund else "out_invoice",
            "partner_id": self.partner_id.id,
            "journal_id": accounting.loan_journal.id,
            "invoice_date": date,
            "date": date,
            "payment_reference": self.name,
            "ref": self.name,
            "mfi_loan_id": self.id,
            "mfi_kind": kind,
            "invoice_line_ids": [Command.create({
                "product_id": product.id, "name": label, "quantity": 1, "price_unit": amount,
                "account_id": (account or product.property_account_income_id).id, "tax_ids": [Command.clear()],
            })],
        })
        move.action_post()
        if refund:
            credit = move.line_ids.filtered(lambda l: l.account_id.account_type == "asset_receivable")
            for line in self._receivable_lines().filtered(lambda l: not l.reconciled).sorted(
                    lambda l: (l.date_maturity or l.date, l.id), reverse=True):
                if credit.reconciled:
                    break
                (credit | line).reconcile()
        return move

    @api.model
    def _cron_daily(self):
        loans = self.search([("state", "=", "active")])
        loans._accrue_penalty()
        loans._mfi_refresh()

    def _mfi_refresh(self):
        """The figures depend on today's date: recompute them (the nightly run)."""
        for name in ("outstanding", "health", "days_past_due", "arrears_amount", "oldest_unpaid_due",
                     "ageing_bucket", "amount_paid", "penalty_accrued", "penalty_paid", "penalty_due"):
            self.env.add_to_compute(self._fields[name], self)
        self.flush_recordset()

    # ------------------------------------------------------------------
    # Early settlement and write-off
    # ------------------------------------------------------------------

    def _settlement_quote(self, today=None):
        """What closes the loan today: interest for the days so far (at least the
        minimum, at most the term), less what is paid, plus default interest due."""
        self.ensure_one()
        today = fields.Date.to_date(today) or fields.Date.context_today(self)
        if self.state != "active":
            raise UserError(self.env._("Loan is not active."))
        self._accrue_penalty(today)
        days = max((today - self.start_date).days + 1, 0)
        interest_days = min(max(days, self.min_interest_days), self.term_days)
        interest = r2(self.principal * self.daily_rate * interest_days)
        new_total = r2(self.principal + interest)
        penalty_due = self.penalty_due
        return {
            "interest_days": interest_days,
            "interest": interest,
            "rebate": r2(max(self.interest - interest, 0)),
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
        if settlement["rebate"]:
            loan._mfi_post_charge("settlement", settlement["rebate"], today, self.env._(
                "Interest not charged: settled after %s days", settlement["interest_days"]),
                refund=True, product=loan.product_id._mfi_products()[1])
        loan.write({"interest": settlement["interest"], "total_repayable": settlement["new_total_payable"]})
        payment = loan._mfi_register_payment(amount, method, reference, today, note=self.env._("Early settlement"))
        rules.audit(self.env, "loan.settled_early", self, {
            "amount": amount, "reference": reference, "interest_days": settlement["interest_days"]})
        return payment

    def action_write_off(self, reason):
        rules.check(self.env, "loans.writeoff")
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise UserError(self.env._("Give a reason."))
        today = fields.Date.context_today(self)
        for loan in self:
            if loan.state != "active":
                raise UserError(self.env._("Only active loans can be written off."))
            loan._accrue_penalty()
            outstanding = loan.outstanding
            if outstanding > 0:
                accounting = loan.company_id._mfi_accounting()
                loan.sudo()._mfi_post_charge(
                    "write_off", outstanding, today, self.env._("Written off: %s", reason), refund=True,
                    account=accounting.bad_debt, product=loan.product_id._mfi_products()[0])
            loan.sudo().write({
                "state": "written_off",
                "written_off_date": today,
                "write_off_reason": reason,
            })
            loan.message_post(body=self.env._(
                "Written off with KES %(amount)s outstanding: %(reason)s",
                amount=f"{outstanding:,.2f}", reason=reason))
            rules.audit(self.env, "loan.written_off", loan, {"outstanding": outstanding, "reason": reason})


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
