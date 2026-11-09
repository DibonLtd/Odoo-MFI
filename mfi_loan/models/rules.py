"""Roan Capital's rules, as the loan portal (roan-loan-app.vercel.app) has them."""

import math

from odoo.exceptions import AccessError
from odoo.tools import float_round

G = "mfi_loan.group_mfi_"
SA = G + "admin"
CEO = G + "ceo"
HO = G + "head_office"
CM = G + "credit_manager"
LO = G + "loan_officer"
FIN = G + "finance"
COL = G + "collections"
AUD = G + "auditor"

# Who may do what: the portal's permission table.
PERMISSIONS = {
    "clients.write": (SA, HO, CM, LO),
    "clients.blacklist": (SA, HO, CEO, CM),
    "loans.create": (SA, HO, CM, LO),
    "loans.disburse": (SA, FIN, HO),
    "loans.writeoff": (SA, CEO),
    "payments.record": (SA, HO, CM, FIN, COL, LO),
    "payments.reverse": (SA, CEO, HO, FIN),
    "collections.write": (SA, HO, CM, COL, LO),
}

# Who decides each approval stage, in order; a Super Admin may decide any stage.
APPROVAL_CHAIN = (CM, CM, CEO)

TERMS = {"two_weeks": 14, "one_month": 30}


def r2(value):
    """Round half up to cents, as the portal does."""
    return float_round(value, precision_digits=2)


def allowed(env, permission):
    return env.su or any(env.user.has_group(group) for group in PERMISSIONS[permission])


def check(env, permission):
    if not allowed(env, permission):
        raise AccessError(env._("You do not have permission to do this."))


def quote(principal, daily_rate, term_days):
    interest = r2(principal * daily_rate * term_days)
    total = r2(principal + interest)
    installment = math.ceil(total / term_days) if term_days else 0
    return {"interest": interest, "total_repayable": total, "installment": installment}
