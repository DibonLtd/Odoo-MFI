from odoo import api, fields, models
from odoo.exceptions import ValidationError

CATEGORIES = [
    ("chattels", "Chattels mortgage"),
    ("logbook", "Logbook (vehicle)"),
    ("title_deed", "Title deed (land)"),
]


class MfiProduct(models.Model):
    _name = "mfi.product"
    _description = "Loan product"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category = fields.Selection(CATEGORIES, required=True)
    daily_rate = fields.Float(
        digits=(6, 4), required=True, default=0.01,
        help="Interest per day as a fraction of the principal: 0.01 is 1% a day. "
        "New applications only; existing loans keep the terms they were issued on.",
    )
    penalty_rate = fields.Float(
        "Default interest", digits=(6, 4), required=True, default=0.01,
        help="Per day, on each daily instalment past its due date and unpaid.",
    )
    min_interest_days = fields.Integer(
        "Minimum interest days on prepayment", required=True, default=14,
    )
    min_amount = fields.Float("Minimum amount", required=True, default=3000)
    max_amount = fields.Float("Maximum amount", required=True, default=100000)

    @api.constrains("min_amount", "max_amount", "daily_rate", "penalty_rate")
    def _check_limits(self):
        for product in self:
            if product.min_amount <= 0 or product.max_amount < product.min_amount:
                raise ValidationError(self.env._("The amount range of %s is not valid.", product.name))
            if product.daily_rate < 0 or product.penalty_rate < 0:
                raise ValidationError(self.env._("Rates cannot be negative."))
