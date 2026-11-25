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
    product_id = fields.Many2one("product.product", "Product", copy=False,
                                 help="Fee income in Accounting; one product per fee (all its bands). Made automatically.")

    def _mfi_product(self):
        """The fee's product: shared by every band of the same fee (same code)."""
        self.ensure_one()
        if not self.product_id:
            band = self.sudo().with_context(active_test=False).search(
                [("code", "=", self.code), ("product_id", "!=", False)], limit=1)
            product = band.product_id or self.env["product.product"]._mfi_service(
                self.env._("Loan fee: %s", self.name.split("(")[0].strip()),
                self.env.company._mfi_accounting().fee)
            self.sudo().product_id = product
        return self.product_id

    def _applies(self, principal, category, first_loan):
        self.ensure_one()
        return (
            (not self.min_principal or principal >= self.min_principal)
            and (not self.max_principal or principal <= self.max_principal)
            and (not self.first_loan_only or first_loan)
            and (not self.product_category or self.product_category == category)
        )
