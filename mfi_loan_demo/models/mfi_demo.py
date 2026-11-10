"""Load and remove the sample data.

Every sample record is created through the real workflow (onboarding, checks,
three approvals, disbursement, day-by-day M-Pesa repayments), then dated on
the day it would have happened, so the dashboard, ageing and reports look like
a lender three months into business. Each record the loader creates directly is
registered under this module, so uninstalling finds and deletes all of it.
"""

import base64
import math
import random
import secrets
import string
from contextlib import contextmanager
from datetime import datetime, time, timedelta

from odoo import api, fields, models

from . import mfi_demo_data as D
from .mfi_demo_apps import AppsLoader, unload_apps

MODULE = "mfi_loan_demo"
PASSWORD_PARAM = "mfi_loan_demo.password"
SAMPLE_FILE = base64.b64encode(b"Sample document for the Microfinance sample data.")
# Tables whose dates the loader moves back to the day an event happened.
DATED = [
    ("mail.message", "date"), ("mfi.audit.log", "date"), ("mfi.collection.note", "create_date"),
    ("res.partner", "create_date"), ("mfi.loan", "create_date"), ("mfi.payment", "create_date"),
    ("mfi.loan.approval", "decided_at"), ("crm.lead", "create_date"), ("helpdesk.ticket", "create_date"),
    ("hr.employee", "create_date"), ("mail.activity", "create_date"),
]


class ResPartner(models.Model):
    _inherit = "res.partner"

    mfi_is_sample = fields.Boolean("Sample record", readonly=True, copy=False)

    def _mfi_messaging_blocked(self):
        return self.mfi_is_sample or super()._mfi_messaging_blocked()


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mfi_demo_password = fields.Char("Sample staff password", compute="_compute_mfi_demo_password")

    def _compute_mfi_demo_password(self):
        password = self.env["ir.config_parameter"].sudo().get_param(PASSWORD_PARAM)
        for settings in self:
            settings.mfi_demo_password = password


class MfiDemo(models.AbstractModel):
    _name = "mfi.demo"
    _description = "Microfinance sample data"

    @api.model
    def _load(self):
        if self.env["ir.model.data"].search_count([("module", "=", MODULE), ("model", "=", "mfi.loan")]):
            return
        _Loader(self.sudo().env).run()

    # ------------------------------------------------------------------
    # Removing
    # ------------------------------------------------------------------

    @api.model
    def _unload(self):
        """Delete every sample record and the staff accounts."""
        env = self.sudo().env
        unload_apps(env)
        data = env["ir.model.data"].search([("module", "=", MODULE), ("name", "=like", "sample_%")])
        ids = {}
        for row in data:
            ids.setdefault(row.model, []).append(row.res_id)
        users = env["res.users"].with_context(active_test=False).browse(ids.get("res.users", [])).exists()
        clients = env["res.partner"].with_context(active_test=False).search([("mfi_is_sample", "=", True)])
        clients |= env["res.partner"].browse(ids.get("res.partner", [])).exists()
        loans = env["mfi.loan"].search([("partner_id", "in", clients.ids)])
        loans |= env["mfi.loan"].browse(ids.get("mfi.loan", [])).exists()
        payments = env["mfi.payment"].search([("loan_id", "in", loans.ids)])
        payments |= env["mfi.payment"].browse(ids.get("mfi.payment", [])).exists()

        Log = env["mfi.audit.log"].with_context(mfi_audit_purge=True)
        logs = Log.search([("user_id", "in", users.ids)])
        for model, records in (("mfi.loan", loans), ("res.partner", clients), ("mfi.payment", payments),
                               ("res.users", users)):
            logs |= Log.search([("res_model", "=", model), ("res_id", "in", records.ids)])
        logs.unlink()
        payments.unlink()
        loans.unlink()
        clients.unlink()
        user_partners = users.partner_id
        for user in users:
            try:
                with env.cr.savepoint():
                    user.unlink()
            except Exception:  # in use somewhere else: keep the record but close the account
                user.write({"active": False})
        for partner in user_partners.exists():
            try:
                with env.cr.savepoint():
                    partner.unlink()
            except Exception:
                partner.write({"active": False})
        data.unlink()
        env["ir.config_parameter"].search([("key", "=", PASSWORD_PARAM)]).unlink()
        # Start numbering again at 1 when nothing real was numbered in the meantime.
        if not env["mfi.loan"].search_count([]):
            env.ref("mfi_loan.seq_mfi_loan").number_next = 1
        if not env["res.partner"].with_context(active_test=False).search_count([("mfi_client_no", "!=", False)]):
            env.ref("mfi_loan.seq_mfi_client").number_next = 1


class _Loader:
    """Creates the sample data; holds what the steps share."""

    def __init__(self, env):
        self.env = env
        self._rng = random.Random(254)
        self._today = fields.Date.context_today(env["res.partner"])
        self._serial = 0
        self._staff = {}
        self._uids = [env.uid]

    def run(self):
        self._staff = self._create_staff()
        self._uids = [user.id for user in self._staff.values()] + [self.env.uid]
        clients = [self._create_individual(spec) for spec in D.INDIVIDUALS]
        clients += [self._create_business(spec) for spec in D.BUSINESSES]
        loans = self.env["mfi.loan"]
        for client_index, category, amount, term, plan, days_ago, details in D.LOANS:
            loans |= self._create_loan(clients[client_index], category, amount, term, plan, days_ago, details)
        self._unmatched_payments()
        self._finish(loans)
        AppsLoader(self).run(clients, loans)

    def _register(self, record, kind):
        self._serial += 1
        self.env["ir.model.data"].create({
            "module": MODULE, "name": f"sample_{kind}_{self._serial}", "model": record._name,
            "res_id": record.id, "noupdate": True,
        })
        return record

    @contextmanager
    def _on(self, day, hour=None):
        """Date what is created inside the block on `day` (Nairobi office hours)."""
        self.env.flush_all()
        marks = {}
        for model, _column in DATED:
            if model in self.env:
                table = self.env[model]._table
                self.env.cr.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}")  # noqa: S608 (fixed names)
                marks[table] = self.env.cr.fetchone()[0]
        yield
        self.env.flush_all()
        hour = hour if hour is not None else self._rng.randint(8, 17)
        # East Africa Time is UTC+3.
        when = datetime.combine(day, time(hour, self._rng.randint(0, 59))) - timedelta(hours=3)
        for model, column in DATED:
            if model not in self.env:
                continue
            table = self.env[model]._table
            self.env.cr.execute(
                f"UPDATE {table} SET {column} = %s WHERE id > %s AND create_uid = ANY(%s)",  # noqa: S608
                [when, marks[table], self._uids])
        self.env.invalidate_all()

    def _day(self, days_ago):
        return self._today - timedelta(days=days_ago)

    # ------------------------------------------------------------------
    # People
    # ------------------------------------------------------------------

    def _create_staff(self):
        password = secrets.token_urlsafe(12)
        self.env["ir.config_parameter"].sudo().set_param(PASSWORD_PARAM, password)
        staff = {}
        for key, name, role in D.STAFF:
            login = f"{key}@{D.STAFF_DOMAIN}"
            user = self.env["res.users"].with_context(no_reset_password=True).create({
                "name": name, "login": login, "email": login, "password": password,
                "notification_type": "inbox",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id,
                                      self.env.ref(f"mfi_loan.group_mfi_{role}").id])],
            })
            staff[key] = self._register(user, "user")
        return staff

    def _unique(self, make, model, field):
        Model = self.env[model].with_context(active_test=False)
        for _attempt in range(50):
            value = make()
            if not Model.search_count([(field, "=", value)]):
                return value
        raise ValueError(f"No free {field}")

    def _phone(self, prefixes=None):
        prefix = self._rng.choice(prefixes or D.SAFARICOM * 3 + D.AIRTEL)
        return self._unique(lambda: prefix + "".join(self._rng.choices(string.digits, k=6)), "res.partner", "phone")

    def _id_number(self):
        return self._unique(lambda: str(self._rng.randint(20000000, 39999999)), "res.partner", "mfi_id_number")

    def _kra_pin(self):
        return "A0" + "".join(self._rng.choices(string.digits, k=8)) + self._rng.choice(string.ascii_uppercase)

    def _kin(self, surname):
        relationship, word = self._rng.choice(D.KIN)
        return (0, 0, {
            "full_name": f"{self._rng.choice(D.OTHER_NAMES)} {surname}", "relationship": f"{relationship} ({word})",
            "id_number": str(self._rng.randint(10000000, 39999999)), "phone": self._phone(),
        })

    def _documents(self, kinds):
        return [(0, 0, {"kind": kind, "file": SAMPLE_FILE, "file_name": f"{kind}_sample.txt"}) for kind in kinds]

    def _onboarded_on(self, client_index):
        """Clients joined over the last three months, before their first loan."""
        first = min((days for index, _c, _a, _t, _p, days, _d in D.LOANS if index == client_index), default=0)
        return self._day(first + self._rng.randint(5, 12))

    def _bank(self, holder):
        return {"mfi_bank_account_name": f"{holder}, {self._rng.choice(D.BANKS)}",
                "mfi_bank_account_number": "".join(self._rng.choices(string.digits, k=13))}

    def _create_individual(self, spec):
        name, business, location, home, county, income, stock = spec
        index = D.INDIVIDUALS.index(spec)
        first, surname = name.split(" ", 1)
        with self._on(self._onboarded_on(index)):
            client = self.env["res.partner"].with_user(self._staff["officer"]).create({
                "name": name, "is_mfi_client": True, "mfi_is_sample": True, "mfi_client_type": "individual",
                "mfi_id_number": self._id_number(), "phone": self._phone(), "mfi_alt_phone": self._phone(),
                "email": f"{first.lower()}.{surname.lower().replace(' ', '')}@example.com",
                "mfi_kra_pin": self._kra_pin(), "country_id": self.env.ref("base.ke").id,
                "mfi_residential_address": home, "mfi_permanent_address": f"P.O. Box {self._rng.randint(100, 9999)}, {county}",
                "mfi_rural_home": f"{county} County", "mfi_business_type": business, "mfi_business_location": location,
                "mfi_daily_income": income, "mfi_stock_value": stock,
                "mfi_stock_turnover": round(self._rng.uniform(2, 8), 1),
                "mfi_mpesa_cashflow_6m": income * 150, "mfi_bank_cashflow_6m": income * 40,
                "mfi_current_loans_count": self._rng.choice([0, 0, 1]),
                "mfi_next_of_kin_ids": [self._kin(surname), self._kin(surname)],
                "mfi_document_ids": self._documents(["national_id", "passport_photo", "mpesa_statement"]),
                **self._bank(name),
            })
        return self._register(client, "client")

    def _create_business(self, spec):
        name, registration, business, location, director, designation, income, stock = spec
        index = len(D.INDIVIDUALS) + D.BUSINESSES.index(spec)
        with self._on(self._onboarded_on(index)):
            client = self.env["res.partner"].with_user(self._staff["officer"]).create({
                "name": name, "is_mfi_client": True, "mfi_is_sample": True, "mfi_client_type": "business",
                "is_company": True, "mfi_id_number": registration, "phone": self._phone(D.SAFARICOM),
                "email": "info@" + "".join(c for c in name.lower() if c.isalnum())[:20] + ".example.com",
                "mfi_kra_pin": "P0" + "".join(self._rng.choices(string.digits, k=8)) + "K",
                "country_id": self.env.ref("base.ke").id,
                "mfi_business_type": business, "mfi_business_location": location,
                "mfi_residential_address": location, "mfi_daily_income": income, "mfi_stock_value": stock,
                "mfi_mpesa_cashflow_6m": income * 160, "mfi_bank_cashflow_6m": income * 90,
                "mfi_contact_name": director, "mfi_contact_designation": designation,
                "mfi_contact_id_number": self._id_number(), "mfi_contact_phone": self._phone(),
                "mfi_document_ids": self._documents(["business_registration", "national_id", "bank_statement",
                                                     "kra_certificate"]),
                **self._bank(name),
            })
        return self._register(client, "client")

    # ------------------------------------------------------------------
    # Loans
    # ------------------------------------------------------------------

    def _security(self, client, category, amount):
        if category == "chattels":
            items, total = [], 0
            for description, quantity, value in self._rng.sample(D.CHATTELS, 3):
                items.append((0, 0, {"description": description, "quantity": quantity, "value": value}))
                total += quantity * value
                if total >= amount * 1.5:
                    break
            return {"chattel_ids": items, "chattels_location": client.mfi_residential_address}
        if category == "logbook":
            reg, make, model, year = self._rng.choice(D.VEHICLES)
            return {"vehicle_reg_no": reg, "vehicle_make": make, "vehicle_model": model, "vehicle_year": year}
        return {"title_no": self._rng.choice(D.LAND), "land_location": client.mfi_business_location,
                "registered_owner": client.mfi_contact_name if client.mfi_client_type == "business" else client.name}

    def _mpesa_ref(self):
        def make():
            return self._rng.choice("TU") + "".join(self._rng.choices(string.ascii_uppercase + string.digits, k=9))
        return self._unique(make, "mfi.payment", "reference")

    def _create_loan(self, client, category, amount, term, plan, days_ago, details):
        officer, finance = self._staff["officer"], self._staff["finance"]
        disbursed = self._day(days_ago)
        applied = disbursed - timedelta(days=4) if days_ago else self._day(self._rng.randint(0, 2))
        with self._on(applied, hour=9):
            loan = self.env["mfi.loan"].with_user(officer).create({
                "partner_id": client.id, "product_id": self.env.ref(f"mfi_loan.product_{category}").id,
                "principal": amount, "term": term,
                "guarantor_name": f"{self._rng.choice(D.OTHER_NAMES)} {self._rng.choice(D.OTHER_NAMES)}",
                "guarantor_id_number": str(self._rng.randint(10000000, 39999999)), "guarantor_phone": self._phone(),
                **self._security(client, category, amount),
            })
        self._register(loan, "loan")
        if plan == "draft":
            return loan
        loan = loan.with_user(officer)
        with self._on(applied, hour=11):
            loan.action_submit()
        if plan == "pending_information":
            loan.write({"house_visit_officer": officer.name})
            return loan
        visit = applied + timedelta(days=1)
        with self._on(visit, hour=15):
            kinds = {"chattels": ["chattels_agreement"], "logbook": ["logbook", "ntsa_report", "valuation_report"],
                     "title_deed": ["title_deed", "valuation_report"]}[category]
            loan.write({
                "house_visit_date": visit, "house_visit_officer": officer.name, "house_visit_applicant_met": True,
                "house_visit_observations": self._rng.choice([
                    "Business visited; stock as declared and well kept. Neighbours confirm the applicant has traded here for years.",
                    "Home and business visited. Applicant present with spouse; security items seen and photographed.",
                    "Premises visited at midday, busy with customers. Records of daily sales shown.",
                ]),
                "upfront_fee_ref": self._mpesa_ref() if loan.upfront_total else False,
                "document_ids": self._documents(kinds + ["signed_agreement", "signed_form"]),
            })
            loan.action_generate_agreement()
            loan.write({"agreement_sent_via": "whatsapp"})
            loan.action_mark_agreement_sent()
            loan.action_send_for_approval()
        stages = {"stage1": 0, "stage2": 1, "stage3": 2, "rejected": 1}.get(plan, 3)
        approvers = [self._staff["credit"], self._staff["credit2"], self._staff["ceo"]]
        decided = visit
        for stage in range(stages):
            decided = min(visit + timedelta(days=1 + stage // 2), disbursed if days_ago else self._today)
            with self._on(decided, hour=10 + stage * 2):
                loan.with_user(approvers[stage]).action_approve(
                    self._rng.choice(["", "Good cash flow.", "Security adequate.", "Repeat client, good record."]))
        office_hours = lambda day, hour: datetime.combine(day, time(hour - 3, 0))  # noqa: E731 (EAT to UTC)
        loan.sudo().write({
            "agreement_generated_at": office_hours(visit, 15), "agreement_sent_at": office_hours(visit, 16),
            "submitted_at": office_hours(visit, 17),
            "approved_at": office_hours(decided, 16) if stages == 3 else False,
        })
        if plan == "rejected":
            with self._on(decided, hour=16):
                loan.with_user(approvers[1]).action_reject(
                    "Title deed is in a third party's name; the registered owner did not consent.")
            return loan
        if plan in ("stage1", "stage2", "stage3", "approved"):
            return loan
        with self._on(disbursed, hour=12):
            method = self._rng.choice(["mpesa", "mpesa", "mpesa", "bank"])
            ref = self._mpesa_ref() if method == "mpesa" else f"FT{disbursed:%y%j}{self._rng.randint(10000, 99999)}"
            loan.with_user(finance).action_disburse(method, ref, disbursed)
        # Disbursing charges default interest up to today; start again from the payout day.
        loan.sudo().write({"penalty_accrued": 0, "penalty_through": disbursed})
        self._repay(loan, plan, details)
        return loan

    def _pay(self, loan, amount, day, method="mpesa"):
        with self._on(day):
            return self.env["mfi.payment"].with_user(self._staff["finance"]).create({
                "loan_id": loan.id, "amount": amount, "method": method, "date": day,
                "reference": self._mpesa_ref() if method == "mpesa" else f"EQ{self._rng.randint(10 ** 8, 10 ** 9)}",
                "payer_phone": loan.partner_id.phone,
            })

    def _due_through(self, loan, day):
        loan._accrue_penalty(day)
        due = sum(max(i.amount_due - i.amount_paid, 0) for i in loan.installment_ids if i.due_date <= day)
        return due + loan.penalty_due

    def _repay(self, loan, plan, details):
        start, today = loan.disbursed_date + timedelta(days=1), self._today
        last = min(today, loan.maturity_date)
        if plan == "late":
            last = today - timedelta(days=details["stopped"] + 1)
        elif plan in ("overdue", "written_off"):
            last = loan.disbursed_date + timedelta(days=details["paid_days"])
        elif plan == "settled":
            last = loan.disbursed_date + timedelta(days=details["settle_after"] - 1)
        day = start
        while day <= last and loan.state == "active":
            gap = self._rng.choice([1, 1, 1, 2, 2, 3]) if plan != "current" else self._rng.choice([1, 1, 2])
            pay_day = min(day + timedelta(days=gap - 1), last)
            if plan == "current" and pay_day == last:
                pay_day = today
            due = self._due_through(loan, pay_day)
            if due > 0.5:
                amount = min(math.ceil(due / 10) * 10, loan.outstanding)
                method = "bank" if amount > 5000 and self._rng.random() < 0.2 else "mpesa"
                self._pay(loan, amount, pay_day, method)
            day = pay_day + timedelta(days=1)
        if plan == "repaid" and loan.state == "active":
            self._due_through(loan, loan.maturity_date)
            self._pay(loan, loan.outstanding, loan.maturity_date)
        elif plan == "settled":
            settle_day = loan.disbursed_date + timedelta(days=details["settle_after"])
            quote = loan._settlement_quote(settle_day)
            with self._on(settle_day):
                loan.with_user(self._staff["finance"]).action_settle(
                    math.ceil(quote["settlement_amount"]), "mpesa", self._mpesa_ref(), today=settle_day)
        elif plan == "written_off":
            day = self._day(details["written_off_ago"])
            with self._on(day):
                loan.with_user(self._staff["ceo"]).action_write_off(
                    "Client relocated; business closed and the chattels could not be traced.")
            loan.sudo().write({"written_off_date": day})
        if details.get("reversal"):
            self._reversal(loan)
        if plan in ("late", "overdue"):
            self._follow_up(loan, plan)

    def _reversal(self, loan):
        """A payment keyed in twice, found and reversed the same day."""
        day = self._day(3)
        duplicate = self._pay(loan, loan.installment, day)
        with self._on(day, hour=16):
            duplicate.with_user(self._staff["headoffice"]).action_reverse(
                "Duplicate entry: same M-Pesa payment recorded twice.")

    def _follow_up(self, loan, plan):
        Note = self.env["mfi.collection.note"].with_user(self._staff["collections"])
        stopped = loan.oldest_unpaid_due or self._day(5)
        first_call = min(stopped + timedelta(days=2), self._today)
        with self._on(first_call, hour=10):
            Note.create({"loan_id": loan.id, "kind": "call",
                         "note": "Called client; says sales are slow this week. Reminded of the daily instalment."})
        with self._on(min(first_call + timedelta(days=1), self._today), hour=11):
            Note.create({"loan_id": loan.id, "kind": "sms", "note": loan.reminder_sms})
        if plan == "overdue":
            visit = min(first_call + timedelta(days=4), self._today)
            with self._on(visit, hour=14):
                Note.create({"loan_id": loan.id, "kind": "visit",
                             "note": "Visited the business with the guarantor. Chattels still at the premises."})
                broken = Note.create({"loan_id": loan.id, "kind": "promise", "note": "Promised to clear arrears.",
                                      "promise_date": visit + timedelta(days=3),
                                      "promise_amount": math.ceil(loan.arrears_amount / 100) * 100})
            with self._on(min(visit + timedelta(days=4), self._today), hour=9):
                broken.action_broken()
        with self._on(self._today, hour=9):
            Note.create({"loan_id": loan.id, "kind": "promise", "note": "Client promised to pay on Friday.",
                         "promise_date": self._today + timedelta(days=self._rng.randint(1, 4)),
                         "promise_amount": math.ceil(min(loan.arrears_amount, 5000) / 100) * 100 or 500})

    def _unmatched_payments(self):
        finance = self._staff["finance"]
        Payment = self.env["mfi.payment"].with_user(finance)
        with self._on(self._day(1), hour=19):
            self._register(Payment.create({
                "amount": 1500, "method": "mpesa", "reference": self._mpesa_ref(),
                "payer_phone": "0799" + "".join(self._rng.choices(string.digits, k=6)),
                "lookup": "Mama Wanjiru", "note": "Paybill account entered as a name.",
            }), "payment")
        with self._on(self._today, hour=8):
            self._register(Payment.create({
                "amount": 2300, "method": "bank", "reference": f"FT{self._today:%y%j}88231",
                "lookup": "RCL 12", "note": "Bank transfer with an incomplete loan number.",
            }), "payment")

    def _finish(self, loans):
        active = loans.filtered(lambda loan: loan.state == "active")
        active._accrue_penalty(self._today)
        loans._update_health(self._today)
        Loan = self.env["mfi.loan"]
        for name in ("last_contact_date", "last_contact_kind", "last_contact_note", "open_promise_date"):
            self.env.add_to_compute(Loan._fields[name], loans)
        self.env.flush_all()
