"""Loans in Odoo Accounting (DECISIONS D-017): Odoo's own objects, set up once per
company from the loan types' defaults. Nobody computes a schedule by hand: the
loan's invoice gets a daily payment term, and Odoo makes the instalments.

* The loan is a customer invoice: principal (loan-type product, principal
  account) and interest (the loan type's interest product). Its payment term
  splits the receivable into one dated line per day.
* The payout is an outbound payment into the principal account, so the
  principal account clears; deducted fees move from it to fee income.
* Repayments are ordinary payments reconciled with the loan's receivable lines,
  oldest due first. Arrears, ageing and reminders come from those lines.
"""

from types import SimpleNamespace

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

KINDS = [
    ("loan", "Loan"),
    ("fee", "Upfront fees"),
    ("disbursement", "Disbursement"),
    ("penalty", "Default interest"),
    ("settlement", "Early settlement rebate"),
    ("write_off", "Write-off"),
]

# role -> (name, account type, code prefix)
ACCOUNTS = {
    "principal": ("Loans to clients: principal", "asset_current", "1300"),
    "interest": ("Loan interest income", "income", "4100"),
    "fee": ("Loan fee income", "income", "4110"),
    "penalty": ("Default interest income", "income", "4120"),
    "bad_debt": ("Loans written off", "expense", "6900"),
}
# method -> (journal name, code, type)
JOURNALS = {
    "loan": ("Loans", "LOAN", "sale"),
    "mpesa": ("M-Pesa", "MPESA", "bank"),
    "bank": ("Bank", None, "bank"),
    "cash": ("Cash", "CSH1", "cash"),
}


class AccountMove(models.Model):
    _inherit = "account.move"

    mfi_loan_id = fields.Many2one("mfi.loan", "Loan", index="btree_not_null", readonly=True, copy=False)
    mfi_kind = fields.Selection(KINDS, "Loan entry", readonly=True, copy=False)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    mfi_loan_id = fields.Many2one("mfi.loan", "Loan", index="btree_not_null", readonly=True, copy=False)

    def action_mfi_match(self, loan):
        """Apply a payment received without a loan (an unknown M-Pesa account) to one."""
        from . import rules  # noqa: PLC0415

        rules.check(self.env, "payments.record")
        self.ensure_one()
        payment = self.sudo()
        if payment.state not in ("paid", "reconciled") or payment.payment_type != "inbound" or payment.is_reconciled:
            raise UserError(self.env._("Only a received payment not yet applied can be matched."))
        if payment.partner_id and payment.partner_id != loan.partner_id:
            raise UserError(self.env._("This payment is from %s, not the loan's client.", payment.partner_id.name))
        if not payment.partner_id:
            payment.action_draft()
            payment.partner_id = loan.partner_id
            payment.action_post()
        payment.mfi_loan_id = loan
        loan._mfi_apply(payment)
        loan.message_post(body=self.env._("Payment %s applied to this loan.", payment.memo or payment.name))
        rules.audit(self.env, "payment.matched", loan, {"payment": payment.name, "amount": payment.amount})

    def action_mfi_reverse(self, reason):
        """Undo a repayment: the payment is cancelled, its reconciliation removed, and
        the loan reopens if it had closed."""
        from . import rules  # noqa: PLC0415

        rules.check(self.env, "payments.reverse")
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise UserError(self.env._("Give a reason."))
        for payment in self.sudo():
            loan = payment.mfi_loan_id
            # Back to draft undoes the reconciliation; the entry is then cancelled,
            # never deleted (it has its number in the journal's sequence).
            payment.action_draft()
            payment.move_id.button_cancel()
            payment.state = "canceled"
            if loan:
                loan.message_post(body=self.env._(
                    "Payment %(ref)s of KES %(amount)s reversed: %(reason)s",
                    ref=payment.memo or payment.name, amount=f"{payment.amount:,.2f}", reason=reason))
                rules.audit(self.env, "payment.reversed", loan, {"payment": payment.name, "reason": reason})


class AccountPartialReconcile(models.Model):
    """Every reconciliation, however it is made (a payment, the bank reconciliation,
    a credit note), passes here: the loan follows its receivable."""

    _inherit = "account.partial.reconcile"

    def _mfi_loans(self):
        return (self.debit_move_id | self.credit_move_id).move_id.mfi_loan_id

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        partials._mfi_loans()._mfi_follow_receivable()
        return partials

    def unlink(self):
        loans = self._mfi_loans()
        result = super().unlink()
        loans._mfi_follow_receivable()
        return result


class AccountPaymentTerm(models.Model):
    _inherit = "account.payment.term"

    mfi_daily_days = fields.Integer("Daily instalments", readonly=True, index="btree_not_null",
                                    help="Made for loans: one equal instalment a day for this many days.")

    @api.model
    def _mfi_daily(self, days, company):
        """The payment term 'daily over N days', made once and reused."""
        term = self.search([("mfi_daily_days", "=", days), ("company_id", "in", (False, company.id))], limit=1)
        if term:
            return term
        share = round(100.0 / days, 6)
        lines = [Command.create({"value": "percent", "value_amount": share, "nb_days": day})
                 for day in range(1, days)]
        lines.append(Command.create({"value": "percent", "value_amount": round(100.0 - share * (days - 1), 6),
                                     "nb_days": days}))
        return self.sudo().create({
            "name": self.env._("Daily over %s days", days),
            "mfi_daily_days": days,
            "display_on_invoice": True,
            "line_ids": [Command.clear(), *lines],
        })


class ResCompany(models.Model):
    _inherit = "res.company"

    mfi_principal_account_id = fields.Many2one("account.account", "Loan principal account")
    mfi_interest_account_id = fields.Many2one("account.account", "Interest income account")
    mfi_fee_account_id = fields.Many2one("account.account", "Fee income account")
    mfi_penalty_account_id = fields.Many2one("account.account", "Default interest account")
    mfi_bad_debt_account_id = fields.Many2one("account.account", "Write-off account")
    mfi_loan_journal_id = fields.Many2one("account.journal", "Loans journal", domain=[("type", "=", "sale")])
    mfi_mpesa_journal_id = fields.Many2one("account.journal", "M-Pesa journal", domain=[("type", "=", "bank")])
    mfi_bank_journal_id = fields.Many2one("account.journal", "Bank journal", domain=[("type", "=", "bank")])
    mfi_cash_journal_id = fields.Many2one("account.journal", "Cash journal", domain=[("type", "=", "cash")])
    mfi_penalty_product_id = fields.Many2one("product.product", "Default interest product")

    def _mfi_outstanding_accounts(self):
        """Repayments and payouts post at once (the loan's balance moves the day the
        money does): each payment method of the loan journals gets the chart's
        outstanding receipts / payments account, as Odoo itself falls back to."""
        Chart = self.env["account.chart.template"].with_context(allowed_company_ids=self.root_id.ids)
        receipts = Chart.ref("account_journal_payment_debit_account_id", raise_if_not_found=False) \
            or self.transfer_account_id
        payments = Chart.ref("account_journal_payment_credit_account_id", raise_if_not_found=False) \
            or self.transfer_account_id
        for journal in self.mfi_mpesa_journal_id | self.mfi_bank_journal_id | self.mfi_cash_journal_id:
            journal.inbound_payment_method_line_ids.filtered(lambda l: not l.payment_account_id).payment_account_id = receipts
            journal.outbound_payment_method_line_ids.filtered(lambda l: not l.payment_account_id).payment_account_id = payments

    def _mfi_accounting(self):
        """The accounts, journals and products loans post to, made where missing.
        Safe to call any time: existing set-up is kept."""
        self.ensure_one()
        company = self.sudo()
        Account = self.env["account.account"].sudo().with_company(company)
        values = {}
        for role, (name, account_type, prefix) in ACCOUNTS.items():
            field = f"mfi_{role}_account_id"
            if not company[field]:
                account = Account.search([("name", "=", name), *Account._check_company_domain(company)], limit=1)
                values[field] = (account or Account.create({
                    "name": name,
                    "code": Account._search_new_account_code(prefix),
                    "account_type": account_type,
                    "reconcile": role == "principal",
                })).id
        Journal = self.env["account.journal"].sudo().with_company(company)
        for method, (name, code, journal_type) in JOURNALS.items():
            field = f"mfi_{method}_journal_id"
            if company[field]:
                continue
            domain = [*Journal._check_company_domain(company), ("type", "=", journal_type)]
            journal = Journal.search(domain + ([("code", "=", code)] if code else []), limit=1)
            values[field] = (journal or Journal.create({
                "name": name, "code": code or Journal._get_next_journal_default_code(journal_type, company),
                "type": journal_type, "company_id": company.id,
            })).id
        if values:
            company.write(values)
        company._mfi_outstanding_accounts()
        if not company.mfi_penalty_product_id:
            company.mfi_penalty_product_id = self.env["product.product"]._mfi_service(
                self.env._("Default interest"), company.mfi_penalty_account_id)
        return SimpleNamespace(
            principal=company.mfi_principal_account_id,
            interest=company.mfi_interest_account_id,
            fee=company.mfi_fee_account_id,
            penalty=company.mfi_penalty_account_id,
            bad_debt=company.mfi_bad_debt_account_id,
            loan_journal=company.mfi_loan_journal_id,
            journals={"mpesa": company.mfi_mpesa_journal_id, "bank": company.mfi_bank_journal_id,
                      "cash": company.mfi_cash_journal_id},
            penalty_product=company.mfi_penalty_product_id,
        )


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _mfi_service(self, name, income_account):
        """A service product for loan lines, with no tax: what Accounting reports group by."""
        return self.sudo().create({
            "name": name,
            "type": "service",
            "sale_ok": True,
            "purchase_ok": False,
            "taxes_id": [Command.clear()],
            "supplier_taxes_id": [Command.clear()],
            "property_account_income_id": income_account.id,
        })
