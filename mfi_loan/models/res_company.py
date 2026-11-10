from odoo import fields, models

from . import rules


class ResCompany(models.Model):
    _inherit = "res.company"

    mfi_tagline = fields.Char("Tagline", default="Believe • Achieve")
    mfi_repay_paybill = fields.Char("Repayment M-Pesa paybill")
    mfi_repay_account_format = fields.Char(
        "Paybill account number", default="Loan S/N",
        help="What clients enter as the account, e.g. Loan S/N.")
    mfi_repay_bank_name = fields.Char("Repayment bank")
    mfi_repay_bank_account_name = fields.Char("Repayment bank account name")
    mfi_repay_bank_account_number = fields.Char("Repayment bank account number")
    mfi_payout_paybill = fields.Char("Payout M-Pesa paybill / shortcode")
    mfi_payout_bank_name = fields.Char("Payout bank")
    mfi_payout_bank_account_name = fields.Char("Payout bank account name")
    mfi_payout_bank_account_number = fields.Char("Payout bank account number")
    mfi_first_loan_fees_upfront = fields.Boolean(
        "Collect membership and application fee upfront on the first loan", default=True,
        help="Non-refundable, paid at application. When off, they are deducted at "
        "disbursement like the other charges.")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mfi_company_email = fields.Char(
        related="company_id.email", readonly=False, string="Company email address")
    mfi_company_phone = fields.Char(related="company_id.phone", readonly=False, string="Company phone")
    mfi_tagline = fields.Char(related="company_id.mfi_tagline", readonly=False)
    mfi_repay_paybill = fields.Char(related="company_id.mfi_repay_paybill", readonly=False)
    mfi_repay_account_format = fields.Char(related="company_id.mfi_repay_account_format", readonly=False)
    mfi_repay_bank_name = fields.Char(related="company_id.mfi_repay_bank_name", readonly=False)
    mfi_repay_bank_account_name = fields.Char(related="company_id.mfi_repay_bank_account_name", readonly=False)
    mfi_repay_bank_account_number = fields.Char(related="company_id.mfi_repay_bank_account_number", readonly=False)
    mfi_payout_paybill = fields.Char(related="company_id.mfi_payout_paybill", readonly=False)
    mfi_payout_bank_name = fields.Char(related="company_id.mfi_payout_bank_name", readonly=False)
    mfi_payout_bank_account_name = fields.Char(related="company_id.mfi_payout_bank_account_name", readonly=False)
    mfi_payout_bank_account_number = fields.Char(
        related="company_id.mfi_payout_bank_account_number", readonly=False)
    mfi_first_loan_fees_upfront = fields.Boolean(
        related="company_id.mfi_first_loan_fees_upfront", readonly=False)

    mfi_session_idle_minutes = fields.Integer(
        "Sign out after idle (minutes)", config_parameter="mfi_loan.session_idle_minutes",
        help="0 switches it off. Applies to every user of this database.")
    mfi_session_max_hours = fields.Integer(
        "Maximum session length (hours)", config_parameter="mfi_loan.session_max_hours",
        help="0 switches it off. Applies to every user of this database.")

    def set_values(self):
        super().set_values()
        if self.env.user.has_group("mfi_loan.group_mfi_user"):
            rules.audit(self.env, "settings.updated", self.company_id)
