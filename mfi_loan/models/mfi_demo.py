import base64
from datetime import timedelta

from odoo import api, fields, models

SAMPLE_FILE = base64.b64encode(b"Sample document for the demo database.")


class MfiDemo(models.AbstractModel):
    """Sample clients and loans for demo databases only (loaded from demo data)."""

    _name = "mfi.demo"
    _description = "Microfinance demo data"

    @api.model
    def _load(self):
        if self.env["mfi.loan"].search_count([]):
            return
        user = lambda name: self.env.ref(f"mfi_loan.demo_user_{name}")  # noqa: E731
        officer, cm1, cm2 = user("officer"), user("credit"), user("credit2")
        ceo, finance = user("ceo"), user("finance")
        product = lambda name: self.env.ref(f"mfi_loan.product_{name}")  # noqa: E731
        today = fields.Date.context_today(self)

        def client(name, phone, id_number):
            return self.env["res.partner"].create({
                "name": name, "phone": phone, "is_mfi_client": True,
                "mfi_client_type": "individual", "mfi_id_number": id_number,
                "mfi_document_ids": [
                    (0, 0, {"kind": kind, "file": SAMPLE_FILE, "file_name": f"{kind}.pdf"})
                    for kind in ("national_id", "passport_photo", "mpesa_statement")
                ],
            })

        def application(partner, kind, principal, term="one_month"):
            vals = {
                "partner_id": partner.id, "product_id": product(kind).id, "principal": principal,
                "term": term, "guarantor_name": "Guarantor of " + partner.name,
                "guarantor_id_number": "2" + partner.mfi_id_number[1:], "guarantor_phone": "0711000000",
            }
            if kind == "chattels":
                vals.update(chattels_location="Kiambu town", chattel_ids=[
                    (0, 0, {"description": "Fridge", "quantity": 1, "value": principal}),
                ])
            elif kind == "logbook":
                vals.update(vehicle_reg_no="KDA 123A", vehicle_make="Toyota",
                            vehicle_model="Probox", vehicle_year="2016")
            else:
                vals.update(title_no="KIAMBU/123", land_location="Kiambu", registered_owner=partner.name)
            return self.env["mfi.loan"].with_user(officer).create(vals)

        def ready(loan):
            loan.action_submit()
            kinds = {"chattels": ["chattels_agreement"], "logbook": ["ntsa_report", "valuation_report", "logbook"],
                     "title_deed": ["title_deed", "valuation_report"]}[loan.product_id.category]
            loan.write({
                "house_visit_date": today, "house_visit_officer": officer.name,
                "house_visit_observations": "Home and business visited; applicant present.",
                "upfront_fee_ref": "DEMO" + loan.name[-5:],
                "document_ids": [(0, 0, {"kind": k, "file": SAMPLE_FILE, "file_name": f"{k}.pdf"})
                                 for k in kinds + ["signed_agreement"]],
            })
            loan.action_generate_agreement()
            loan.action_send_for_approval()

        def approved(loan):
            ready(loan)
            loan.with_user(cm1).action_approve()
            loan.with_user(cm2).action_approve()
            loan.with_user(ceo).action_approve()

        def active(loan, days_ago, paid=None):
            """Disburse days_ago; paid(loan) is the amount paid yesterday, worked out after
            disbursement because default interest is charged from then and is paid first."""
            approved(loan)
            loan.with_user(finance).action_disburse("mpesa", "DSB" + loan.name[-5:], today - timedelta(days=days_ago))
            paid = paid(loan) if paid else 0
            if paid:
                self.env["mfi.payment"].with_user(finance).create({
                    "loan_id": loan.id, "amount": paid, "method": "mpesa",
                    "reference": "PAY" + loan.name[-5:], "date": today - timedelta(days=1),
                })

        application(client("Wanjiku Kamau", "0712345601", "30111001"), "chattels", 10000)
        application(client("Otieno Mutua", "0712345602", "30111002"), "logbook", 50000).action_submit()
        third = application(client("Achieng Njeri", "0712345603", "30111003"), "title_deed", 80000)
        ready(third)
        third.with_user(cm1).action_approve()
        approved(application(client("Kamau Wairimu", "0712345604", "30111004"), "chattels", 20000, "two_weeks"))

        # Current: the 4 instalments due before today, and the default interest, paid.
        active(application(client("Akinyi Barasa", "0712345605", "30111005"), "chattels", 15000),
               5, paid=lambda loan: loan.installment * 4 + loan.penalty_due)
        active(application(client("Mwangi Chebet", "0712345606", "30111006"), "logbook", 30000),
               12, paid=lambda loan: loan.installment * 3)
        active(application(client("Naliaka Odhiambo", "0712345607", "30111007"), "chattels", 10000, "two_weeks"),
               25, paid=lambda loan: 2000)
        active(application(client("Kipchoge Atieno", "0712345608", "30111008"), "chattels", 5000, "two_weeks"),
               20, paid=lambda loan: loan.outstanding)

        rejected = application(client("Wairimu Kari", "0712345609", "30111009"), "title_deed", 40000)
        ready(rejected)
        rejected.with_user(cm1).action_reject("Title deed is in a third party's name.")

        self.env["mfi.payment"].with_user(finance).create({
            "amount": 1500, "method": "mpesa", "reference": "UNMATCHED001",
            "payer_phone": "0799000000", "lookup": "unknown account",
        })
        self.env["mfi.loan"]._cron_daily()
