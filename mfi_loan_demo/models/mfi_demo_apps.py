"""Sample data for the other Odoo apps: CRM, Helpdesk, Employees and Accounting.

Each app is loaded only when it is installed, inside a savepoint, so a problem
in one app is logged and never stops the rest. No email goes out: tracking and
stage templates are switched off and sample addresses are @example.com.

Accounting uses journals of its own (sample loan fees, sample supplier bills,
an M-Pesa Paybill bank journal), so real numbering is never touched and
removing the sample data deletes the journals whole.
"""

import logging
import math
from datetime import datetime, time, timedelta

from odoo import Command
from odoo.fields import Domain

from . import mfi_demo_data as D

_logger = logging.getLogger(__name__)

QUIET = {"tracking_disable": True, "mail_create_nolog": True, "mail_create_nosubscribe": True,
         "mail_notrack": True, "mail_auto_subscribe_no_notify": True, "mail_activity_quick_update": True}

# Deleted first to last when the sample data is removed.
UNLOAD_ORDER = [
    "account.payment", "account.move", "account.journal", "account.account",
    "helpdesk.ticket", "helpdesk.sla", "helpdesk.team", "helpdesk.ticket.type",
    "crm.lead", "crm.team", "crm.lost.reason", "utm.source",
    "hr.employee", "hr.job", "hr.department", "hr.work.location",
]


def _utc(day, hour):
    """A Nairobi office hour on `day`, in UTC as Odoo stores it."""
    return datetime.combine(day, time(hour - 3, 0))


class AppsLoader:
    def __init__(self, loader):
        self.loader = loader
        self.env = loader.env(context=dict(loader.env.context, **QUIET))
        self.rng = loader._rng
        self.today = loader._today

    def run(self, clients, loans):
        self._grant_app_access()
        for model, load in (("hr.employee", self._employees), ("crm.lead", self._crm),
                            ("helpdesk.ticket", self._helpdesk), ("account.move", self._accounting)):
            if model not in self.env:
                continue
            try:
                with self.env.cr.savepoint():
                    load(clients, loans)
            except Exception:
                _logger.warning("Sample data for %s was not loaded", model, exc_info=True)

    def _register(self, records, kind):
        for record in records:
            self.loader._register(record, kind)
        return records

    def _grant_app_access(self):
        for key, xmlids in D.STAFF_APP_GROUPS.items():
            groups = [self.env.ref(x, raise_if_not_found=False) for x in xmlids]
            groups = [g.id for g in groups if g]
            if groups:
                self.loader._staff[key].write({"group_ids": [Command.link(g) for g in groups]})

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------

    def _employees(self, clients, loans):
        company = self.env.company
        location = self._register(self.env["hr.work.location"].create({
            "name": "Head office (sample)", "location_type": "office", "address_id": company.partner_id.id,
        }), "work_location")
        field = self._register(self.env["hr.work.location"].create({
            "name": "Field visits (sample)", "location_type": "other", "address_id": company.partner_id.id,
        }), "work_location")
        departments = {name: self._register(self.env["hr.department"].create({"name": f"{name} (sample)"}),
                                             "department") for name in D.DEPARTMENTS}
        jobs = {}
        for name, description in D.POSITIONS.items():
            jobs[name] = self._register(self.env["hr.job"].create({
                "name": f"{name} (sample)", "description": f"<p>{description}</p>",
            }), "job")
        employees = {}
        for key, name, position, department, manager, sex in D.EMPLOYEES:
            user = self.loader._staff.get(key) if key else None
            first, last = name.lower().split(" ", 1)
            phone = self.loader._phone()
            with self.loader._on(self.today - timedelta(days=self.rng.randint(120, 400))):
                employee = self.env["hr.employee"].create({
                    "name": name, "user_id": user.id if user else False,
                    "job_id": jobs[position].id, "job_title": position,
                    "department_id": departments[department].id,
                    "parent_id": employees[manager].id if manager else False,
                    "work_location_id": (field if position in ("Loan Officer", "Collections Officer")
                                         else location).id,
                    "work_email": user.login if user else f"{first}.{last}@{D.STAFF_DOMAIN}",
                    "mobile_phone": phone, "work_phone": phone,
                    "private_phone": self.loader._phone(), "sex": sex,
                    "identification_id": str(self.rng.randint(20000000, 39999999)),
                    "birthday": self.today - timedelta(days=365 * self.rng.randint(24, 52) + self.rng.randint(0, 364)),
                    "emergency_contact": f"{self.rng.choice(D.OTHER_NAMES)} {name.split(' ')[-1]}",
                    "emergency_phone": self.loader._phone(),
                    "private_email": f"{first}.{last}@example.com",
                })
            employees[key or name] = self._register(employee, "employee")
        for department in departments.values():
            heads = [e for e in employees.values() if e.department_id == department]
            if heads:
                department.manager_id = heads[0]

    # ------------------------------------------------------------------
    # CRM: loan enquiries
    # ------------------------------------------------------------------

    def _crm(self, clients, loans):
        staff = self.loader._staff
        team = self._register(self.env["crm.team"].create({
            "name": "Loan enquiries (sample)", "user_id": staff["headoffice"].id,
            "member_ids": [Command.set([staff["officer"].id, staff["credit"].id, staff["credit2"].id])],
        }), "crm_team")
        sources = {name: self._register(self.env["utm.source"].create({"name": f"{name} (sample)"}), "utm_source")
                   for name in D.LEAD_SOURCES}
        reasons = {name: self._register(self.env["crm.lost.reason"].create({"name": f"{name} (sample)"}),
                                        "lost_reason") for name in D.LOST_REASONS}
        stages = self.env["crm.stage"].search([("is_won", "=", False)], order="sequence, id")
        stage_for = {"new": stages[:1], "qualified": stages[1:2] or stages[:1],
                     "proposition": stages[2:3] or stages[-1:]}
        Lead = self.env["crm.lead"]
        products = {"chattels": "Chattels mortgage loan", "logbook": "Logbook loan", "title_deed": "Title deed loan"}

        def lead(name, phone, business, place, product, amount, source, outcome, days_ago, partner=None):
            day = self.today - timedelta(days=days_ago)
            with self.loader._on(day):
                record = Lead.create({
                    "name": f"{products[product]}, KES {amount:,}: {name}",
                    "type": "opportunity", "team_id": team.id,
                    "user_id": self.rng.choice([staff["officer"], staff["credit"]]).id,
                    # With a client, the contact details come from the client (and would be written back).
                    **({"partner_id": partner.id} if partner else {
                        "contact_name": name, "phone": phone,
                        "email_from": f"{name.split(' ')[0].lower()}@example.com",
                        "city": place.split(", ")[-1], "country_id": self.env.ref("base.ke").id,
                    }),
                    "expected_revenue": amount, "source_id": sources[source].id,
                    "date_deadline": day + timedelta(days=7),
                    "description": f"<p>{business} in {place}. Asks for KES {amount:,} "
                                   f"({products[product].lower()}).</p>",
                    "priority": self.rng.choice(["0", "1", "1", "2"]),
                })
            self._register(record, "lead")
            if outcome == "won":
                with self.loader._on(day + timedelta(days=2)):
                    record.action_set_won()
                record.sudo().write({"date_closed": _utc(day + timedelta(days=2), 15)})
            elif outcome.startswith("lost:"):
                with self.loader._on(day + timedelta(days=3)):
                    record.action_set_lost(lost_reason_id=reasons[outcome[5:]].id)
                record.sudo().write({"date_closed": _utc(day + timedelta(days=3), 15)})
            else:
                if stage_for[outcome]:
                    record.stage_id = stage_for[outcome]
                with self.loader._on(day):
                    record.activity_schedule(
                        "mail.mail_activity_data_call", date_deadline=self.today + timedelta(days=self.rng.randint(0, 3)),
                        summary=self.rng.choice(["Call to book the house visit", "Ask for the 6-month M-Pesa statement",
                                                 "Confirm the security documents"]),
                        user_id=record.user_id.id)
            return record

        for spec in D.LEADS:
            lead(*spec)
        # The clients who came in as enquiries: won, a few days before their first loan.
        for loan in loans.filtered(lambda loan: loan.disbursed_date)[:8]:
            client = loan.partner_id
            days_ago = (self.today - loan.disbursed_date).days + 6
            lead(client.name, client.phone, client.mfi_business_type or "Business",
                 client.mfi_business_location or "Nairobi", loan.product_id.category, int(loan.principal),
                 self.rng.choice(D.LEAD_SOURCES), "won", days_ago, partner=client)

    # ------------------------------------------------------------------
    # Helpdesk: complaints and queries
    # ------------------------------------------------------------------

    def _helpdesk(self, clients, loans):
        staff = self.loader._staff
        team = self._register(self.env["helpdesk.team"].create({
            "name": "Client care (sample)", "use_sla": True,
            "member_ids": [Command.set([staff["headoffice"].id, staff["credit"].id, staff["collections"].id])],
        }), "helpdesk_team")
        stages = team.stage_ids.sorted(lambda s: (s.sequence, s.id))
        open_stages, closed = stages.filtered(lambda s: not s.fold), stages.filtered("fold")
        new, in_progress = open_stages[:1], open_stages[1:2] or open_stages[:1]
        solved, cancelled = closed[:1], closed[1:2] or closed[:1]
        hours = (team.resource_calendar_id.hours_per_day or 8)
        acknowledge = resolve = self.env["helpdesk.sla"]
        if in_progress and in_progress != new:
            acknowledge = self._register(self.env["helpdesk.sla"].create({
                "name": "Acknowledge within 7 days (sample)", "team_id": team.id,
                "stage_id": in_progress.id, "time": 5 * hours,
            }), "sla")
        if solved:
            resolve = self._register(self.env["helpdesk.sla"].create({
                "name": "Resolve within 30 days, CBK reg 40 (sample)", "team_id": team.id,
                "stage_id": solved.id, "time": 22 * hours, "exclude_stage_ids": [],
            }), "sla")
        types = {name: self._register(self.env["helpdesk.ticket.type"].create({"name": f"{name} (sample)"}),
                                      "ticket_type") for name in D.TICKET_TYPES}
        Ticket = self.env["helpdesk.ticket"]
        tickets, reached = Ticket, {}
        for client_index, subject, kind, description, outcome, days_ago, priority in D.TICKETS:
            client = clients[client_index]
            opened = self.today - timedelta(days=days_ago)
            with self.loader._on(opened):
                ticket = Ticket.create({
                    "name": subject, "team_id": team.id, "partner_id": client.id,
                    "ticket_type_id": types[kind].id, "priority": priority,
                    "description": f"<p>{description}</p>",
                    "user_id": (staff["collections"] if "collect" in subject.lower() or "pay" in subject.lower()
                                else staff["credit"]).id,
                    "stage_id": new.id,
                })
            self._register(ticket, "ticket")
            tickets |= ticket
            acknowledged = min(opened + timedelta(days=self.rng.randint(0, 2)), self.today)
            if outcome in ("in_progress", "solved") and in_progress:
                ticket.stage_id = in_progress
                reached.setdefault(ticket.id, {})[acknowledge.id] = _utc(acknowledged, 11)
            if outcome == "solved" and solved:
                closed_on = min(opened + timedelta(days=self.rng.randint(3, 12)), self.today)
                ticket.stage_id = solved
                reached.setdefault(ticket.id, {})[resolve.id] = _utc(closed_on, 16)
                ticket.sudo().write({"close_date": _utc(closed_on, 16)})
            elif outcome == "cancelled" and cancelled:
                ticket.stage_id = cancelled
                ticket.sudo().write({"close_date": _utc(opened + timedelta(days=2), 12)})
        self._refresh_sla(tickets, reached)

    def _refresh_sla(self, tickets, reached):
        """Recompute the SLA deadlines from the backdated opening dates, and set when
        each target was reached to the day it happened."""
        env, cr = self.env, self.env.cr
        env.flush_all()
        statuses = tickets.sla_status_ids
        if not statuses:
            return
        cr.execute("UPDATE helpdesk_sla_status SET deadline = NULL WHERE id = ANY(%s)", [statuses.ids])
        for status in statuses:
            when = reached.get(status.ticket_id.id, {}).get(status.sla_id.id)
            if when and status.reached_datetime:
                cr.execute("UPDATE helpdesk_sla_status SET reached_datetime = %s WHERE id = %s", [when, status.id])
        env.invalidate_all()
        env.add_to_compute(statuses._fields["deadline"], statuses)
        env.flush_all()
        statuses.modified(["deadline", "reached_datetime"])
        env.flush_all()

    # ------------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------------

    def _accounting(self, clients, loans):
        company = self.env.company
        Account = self.env["account.account"].with_company(company)
        in_company = Account._check_company_domain(company)
        income = Account.search(in_company & Domain("account_type", "=", "income"), limit=1)
        expense = Account.search(in_company & Domain("account_type", "=", "expense"), limit=1)
        if not (income and expense):
            _logger.info("No chart of accounts: no sample accounting data")
            return
        Journal = self.env["account.journal"].with_company(company)

        def code(prefix):
            for n in range(10):
                candidate = f"{prefix}{n or ''}"[:5]
                if not Journal.search_count([("code", "=", candidate), ("company_id", "=", company.id)]):
                    return candidate
            raise ValueError("No free journal code")

        sales = self._register(Journal.create({
            "name": "Loan fees (sample)", "code": code("SFEE"), "type": "sale",
            "default_account_id": income.id, "company_id": company.id,
        }), "journal")
        bills = self._register(Journal.create({
            "name": "Supplier bills (sample)", "code": code("SBIL"), "type": "purchase",
            "default_account_id": expense.id, "company_id": company.id,
        }), "journal")
        mpesa = Journal.create({"name": "M-Pesa Paybill (sample)", "code": code("SMPS"), "type": "bank",
                                "company_id": company.id})
        self._register(mpesa.default_account_id, "account")  # deleted after the journal
        self._register(mpesa, "journal")
        vat = self.env["account.tax"].search([
            ("company_id", "=", company.id), ("type_tax_use", "=", "purchase"),
            ("amount", "=", 16), ("amount_type", "=", "percent")], limit=1)

        Move = self.env["account.move"].with_company(company)

        def pay(move, day, memo):
            wizard = self.env["account.payment.register"].with_context(
                active_model="account.move", active_ids=move.ids).create({
                    "payment_date": day, "journal_id": mpesa.id, "communication": memo})
            self._register(wizard._create_payments(), "payment")

        # Fees on each disbursed sample loan, invoiced on the payout day and paid at once.
        for loan in loans.filtered(lambda loan: loan.disbursed_date and loan.fee_line_ids):
            day = loan.disbursed_date
            invoice = Move.create({
                "move_type": "out_invoice", "journal_id": sales.id, "partner_id": loan.partner_id.id,
                "invoice_date": day, "date": day, "ref": loan.name,
                "invoice_line_ids": [Command.create({
                    "name": f"{fee.name}, {loan.name}", "quantity": 1, "price_unit": fee.amount,
                    "account_id": income.id, "tax_ids": [Command.clear()],  # financial services: VAT exempt
                }) for fee in loan.fee_line_ids],
            })
            invoice.action_post()
            self._register(invoice, "invoice")
            pay(invoice, day, f"{loan.name} fees, {loan.disbursement_ref}")

        # Three months of supplier bills; this month's are still open.
        sample = self.env["res.partner"]
        for name, what, amount, with_vat in D.VENDORS:
            vendor = sample.create({"name": f"{name} (sample)", "is_company": True, "mfi_is_sample": True,
                                    "country_id": self.env.ref("base.ke").id,
                                    "email": "accounts@" + "".join(c for c in name.lower() if c.isalnum())[:16]
                                             + ".example.com"})
            for months_ago in (2, 1, 0):
                first_of_month = (self.today.replace(day=1) - timedelta(days=31 * months_ago)).replace(day=1)
                day = min(first_of_month + timedelta(days=self.rng.randint(2, 8)), self.today)
                bill = Move.create({
                    "move_type": "in_invoice", "journal_id": bills.id, "partner_id": vendor.id,
                    "invoice_date": day, "date": day,
                    "ref": f"INV-{day:%y%m}-{self.rng.randint(100, 999)}",
                    "invoice_line_ids": [Command.create({
                        "name": f"{what}, {day:%B %Y}", "quantity": 1,
                        "price_unit": math.ceil(amount * self.rng.uniform(0.85, 1.15) / 10) * 10,
                        "account_id": expense.id,
                        "tax_ids": [Command.set(vat.ids if with_vat else [])],
                    })],
                })
                bill.action_post()
                self._register(bill, "bill")
                if months_ago:
                    pay(bill, min(day + timedelta(days=self.rng.randint(5, 20)), self.today), bill.ref)
            self.loader._register(vendor, "vendor")


def unload_apps(env):
    """Delete the other apps' sample records, in an order that respects their links."""
    data = env["ir.model.data"].search([("module", "=", "mfi_loan_demo"), ("name", "=like", "sample_%"),
                                        ("model", "in", UNLOAD_ORDER)])
    by_model = {}
    for row in data:
        by_model.setdefault(row.model, []).append(row.res_id)
    env = env(context=dict(env.context, **QUIET, force_delete=True, active_test=False))
    for model in UNLOAD_ORDER:
        if model not in env or model not in by_model:
            continue
        records = env[model].browse(by_model[model]).exists()
        if model == "account.payment":
            records.filtered(lambda p: p.state != "draft").action_draft()
        elif model == "account.move":
            records.filtered(lambda m: m.state != "draft").button_draft()
        elif model == "hr.employee":
            contacts = records.work_contact_id - records.user_id.partner_id
        for record in records:
            try:
                with env.cr.savepoint():
                    record.unlink()
            except Exception:
                _logger.warning("Could not delete sample %s %s", model, record.id, exc_info=True)
                if "active" in record._fields:
                    record.write({"active": False})
        if model == "hr.employee":
            for contact in contacts.exists():
                try:
                    with env.cr.savepoint():
                        contact.unlink()
                except Exception:
                    contact.write({"active": False})
