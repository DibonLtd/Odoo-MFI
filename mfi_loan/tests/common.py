import base64
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, new_test_user

FILE = base64.b64encode(b"test document")


class MfiCase(TransactionCase):
    """Users for every role, one complete client, and helpers to walk a loan along."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if "mfi.demo" in cls.env:  # the sample data module is installed: start from an empty book
            cls.env["mfi.demo"]._unload()

        def user(login, *groups):
            names = ",".join(f"mfi_loan.group_mfi_{g}" for g in groups)
            return new_test_user(cls.env, login=login, groups=f"base.group_user,{names}")

        cls.officer = user("mfi_officer", "loan_officer")
        cls.cm1 = user("mfi_cm1", "credit_manager")
        cls.cm2 = user("mfi_cm2", "credit_manager")
        cls.ceo = user("mfi_ceo", "ceo")
        cls.head_office = user("mfi_ho", "head_office")
        cls.finance = user("mfi_finance", "finance")
        cls.collections = user("mfi_collections", "collections")
        cls.auditor = user("mfi_auditor", "auditor")
        cls.admin = user("mfi_admin", "admin")
        cls.chattels = cls.env.ref("mfi_loan.product_chattels")
        cls.logbook = cls.env.ref("mfi_loan.product_logbook")
        cls.client = cls._new_client("Test Borrower", "12345678", "0712345678")
        cls.today = fields.Date.today()

    @classmethod
    def _new_client(cls, name, id_number, phone, **extra):
        return cls.env["res.partner"].create({
            "name": name,
            "phone": phone,
            "email": f"{id_number}@example.com",
            "is_mfi_client": True,
            "mfi_client_type": "individual",
            "mfi_id_number": id_number,
            "mfi_document_ids": [
                (0, 0, {"kind": kind, "file": FILE, "file_name": f"{kind}.pdf"})
                for kind in ("national_id", "passport_photo", "mpesa_statement")
            ],
            **extra,
        })

    def _new_loan(self, principal=10000, by=None, term="one_month", product=None, client=None):
        product = product or self.chattels
        vals = {
            "partner_id": (client or self.client).id, "product_id": product.id, "principal": principal,
            "term": term, "guarantor_name": "Guarantor", "guarantor_id_number": "87654321",
            "guarantor_phone": "0722000000",
        }
        if product.category == "chattels":
            vals.update(chattels_location="Thika",
                        chattel_ids=[(0, 0, {"description": "Sofa set", "quantity": 1, "value": principal})])
        return self.env["mfi.loan"].with_user(by or self.officer).create(vals)

    def _ready(self, loan):
        loan.action_submit()
        loan.write({
            "house_visit_date": self.today,
            "house_visit_officer": "Officer",
            "house_visit_observations": "Business premises seen and stocked.",
            "upfront_fee_ref": "qwe123rty",
            "document_ids": [(0, 0, {"kind": k, "file": FILE, "file_name": f"{k}.pdf"})
                             for k in ("chattels_agreement", "signed_agreement")],
        })
        loan.action_generate_agreement()
        loan.action_send_for_approval()

    def _approved(self, loan):
        self._ready(loan)
        loan.with_user(self.cm1).action_approve()
        loan.with_user(self.cm2).action_approve()
        loan.with_user(self.ceo).action_approve()

    def _active(self, loan, days_ago=0):
        self._approved(loan)
        loan.with_user(self.finance).action_disburse(
            "mpesa", f"DSB{loan.id}", self.today - timedelta(days=days_ago))
        return loan

    def _pay(self, loan, amount, ref, by=None, **kw):
        return self.env["mfi.payment"].with_user(by or self.finance).create(
            {"loan_id": loan.id, "amount": amount, "method": "mpesa", "reference": ref, **kw})
