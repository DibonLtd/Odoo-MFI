from odoo import fields, models

from .mfi_product import CATEGORIES


class MfiFee(models.Model):
    """A fee charged on a loan. A banded fee is one record per band."""

    _name = "mfi.fee"
    _description = "Loan fee"
    _order = "sequence, min_principal, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Groups the bands of one fee, e.g. application.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    amount = fields.Float(required=True)
    min_principal = fields.Float(help="Applies from this principal; 0 for no lower limit.")
    max_principal = fields.Float(help="Applies up to this principal; 0 for no upper limit.")
    product_category = fields.Selection(
        CATEGORIES, help="Only for loans of this kind; empty for every loan."
    )
    first_loan_only = fields.Boolean(help="Charged on a client's first loan only.")
    upfront_on_first_loan = fields.Boolean(
        help="On a first loan, paid before approval instead of deducted from the payout."
    )

    def _applies(self, principal, category, first_loan):
        self.ensure_one()
        return (
            (not self.min_principal or principal >= self.min_principal)
            and (not self.max_principal or principal <= self.max_principal)
            and (not self.first_loan_only or first_loan)
            and (not self.product_category or self.product_category == category)
        )
