import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from . import rules

CLIENT_DOCUMENT_KINDS = [
    ("national_id", "National ID"),
    ("passport_photo", "Passport photo"),
    ("mpesa_statement", "M-Pesa statement (6 months)"),
    ("bank_statement", "Bank statement (6 months)"),
    ("business_registration", "Business registration certificate"),
    ("kra_certificate", "KRA PIN certificate"),
    ("other", "Other"),
]
LOAN_DOCUMENT_KINDS = [
    ("logbook", "Logbook"),
    ("ntsa_report", "NTSA verification report"),
    ("valuation_report", "Valuation report"),
    ("title_deed", "Title deed (original, updated)"),
    ("chattels_agreement", "Signed chattels mortgage agreement"),
    ("signed_agreement", "Signed loan agreement"),
    ("signed_form", "Signed application form"),
    ("signature", "Client signature"),
]
# Fields the onboarding rules check.
CLIENT_RULE_FIELDS = ("is_mfi_client", "name", "mfi_client_type", "email", "phone",
                      "mfi_kra_pin", "mfi_id_number", "mfi_contact_name", "mfi_date_of_birth")
NAME_PARTS = ("mfi_first_name", "mfi_middle_name", "mfi_last_name")
# Once a client is in the lending service, these change only through it
# (the onboarding screen), never on the local copy (DECISIONS D-004).
LOCKED_AFTER_PUSH = {
    "name", *NAME_PARTS, "mfi_client_type", "mfi_id_type", "mfi_id_number", "mfi_date_of_birth",
    "mfi_kra_pin", "phone", "email", "mfi_county", "mfi_town", "mfi_street", "mfi_landmark",
    "mfi_consent_to_checks", "is_mfi_client",
}


# Changes to these are recorded in the audit log (which fields, not their values).
AUDITED_CLIENT_FIELDS = {
    "name", "mfi_client_type", "mfi_id_number", "phone", "email", "mfi_alt_phone", "mfi_kra_pin",
    "mfi_bank_account_name", "mfi_bank_account_number", "mfi_contact_name", "mfi_contact_id_number",
    "mfi_contact_phone", "mfi_residential_address", "mfi_business_location",
    *NAME_PARTS, "mfi_id_type", "mfi_date_of_birth", "mfi_consent_to_checks",
    "mfi_county", "mfi_town", "mfi_street", "mfi_landmark",
}


def _differs(record, name, value):
    """Whether writing ``value`` would change the field (forms resend unchanged values)."""
    current = record._fields[name].convert_to_write(record[name], record)
    return str(current or "") != str(value or "")


def compose_name(first, middle, last):
    return " ".join(part.strip() for part in (first, middle, last) if part and part.strip())


def mask_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    return f"•••• ••• {digits[-3:]}" if digits else ""


class MfiClientDocument(models.Model):
    _name = "mfi.client.document"
    _description = "Client or loan document"
    _order = "id desc"

    partner_id = fields.Many2one("res.partner", "Client", required=True, ondelete="cascade", index=True)
    loan_id = fields.Many2one("mfi.loan", ondelete="cascade", index=True,
                              help="Set for a document that belongs to one application.")
    kind = fields.Selection(CLIENT_DOCUMENT_KINDS + LOAN_DOCUMENT_KINDS, required=True)
    file = fields.Binary(attachment=True)
    file_name = fields.Char()
    note = fields.Char()
    lending_document_id = fields.Char("Lending service document", readonly=True, copy=False, index=True)
    lending_stored = fields.Boolean("Stored in the lending service", readonly=True, copy=False,
                                    help="The lending service has this document; the file was removed from Odoo.")

    @api.constrains("file", "lending_stored")
    def _check_file(self):
        for document in self:
            if not document.file and not document.lending_stored:
                raise ValidationError(self.env._("Attach the file."))

    @api.model_create_multi
    def create(self, vals_list):
        rules.check(self.env, "clients.write")
        for vals in vals_list:
            if vals.get("loan_id") and not vals.get("partner_id"):
                vals["partner_id"] = self.env["mfi.loan"].browse(vals["loan_id"]).partner_id.id
        documents = super().create(vals_list)
        for document in documents:
            rules.audit(self.env, "document.uploaded", document.loan_id or document.partner_id,
                        {"kind": document.kind, "file": document.file_name})
        return documents


class MfiNextOfKin(models.Model):
    _name = "mfi.next.of.kin"
    _description = "Client's next of kin"
    _order = "id"

    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade", index=True)
    full_name = fields.Char(required=True)
    relationship = fields.Char()
    id_number = fields.Char("ID number")
    phone = fields.Char()
    alt_phone = fields.Char("Alternate phone")
    email = fields.Char()
    residential_address = fields.Char()
    permanent_address = fields.Char()
    business_type = fields.Char()
    business_location = fields.Char()
    is_primary = fields.Boolean("Primary", help="The next of kin sent to the lending service.")


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_mfi_client = fields.Boolean("Microfinance client")
    mfi_client_no = fields.Char("Client no.", readonly=True, copy=False, index=True)
    mfi_client_type = fields.Selection(
        [("individual", "Individual"), ("business", "Business")], "Client type", default="individual",
        help="Individual: a person borrowing in their own name, with a national ID. "
        "Business: a registered company or business borrowing in its own name.",
    )
    mfi_first_name = fields.Char("First name")
    mfi_middle_name = fields.Char("Middle name")
    mfi_last_name = fields.Char("Last name")
    mfi_id_type = fields.Selection(
        [("national_id", "National ID"), ("alien_id", "Alien ID"), ("passport", "Passport")],
        "ID type", default="national_id")
    mfi_date_of_birth = fields.Date("Date of birth")
    mfi_consent_to_checks = fields.Boolean(
        "Consent to checks", copy=False, tracking=True,
        help="The client agrees to the identity, KRA PIN and screening checks. Record it only when they have.")
    mfi_consent_at = fields.Datetime("Consent recorded at", readonly=True, copy=False)
    mfi_consent_by = fields.Many2one("res.users", "Consent recorded by", readonly=True, copy=False)
    mfi_county = fields.Char("County")
    mfi_town = fields.Char("Town")
    mfi_street = fields.Char("Street or road")
    mfi_landmark = fields.Char("Landmark")
    # The lending service: a reference only (DECISIONS D-004).
    mfi_lending_client_id = fields.Char("Lending service id", readonly=True, copy=False, index=True)
    mfi_lending_sync = fields.Selection(
        [("local", "Only in Odoo"), ("in_backend", "In the lending service"), ("push_failed", "Not sent: see the log")],
        "Lending service", default="local", readonly=True, copy=False, index=True,
        help="Whether this client has been created in the lending service. Its state there is read live.")
    mfi_lending_pushed_at = fields.Datetime("Sent at", readonly=True, copy=False)
    mfi_lending_pushed_by = fields.Many2one("res.users", "Sent by", readonly=True, copy=False)

    _mfi_lending_client_unique = models.Constraint(
        "unique(mfi_lending_client_id)",
        "Another client is already linked to this lending service client.",
    )

    mfi_id_number = fields.Char(
        "ID / registration number",
        groups="mfi_loan.group_mfi_loan_officer,mfi_loan.group_mfi_credit_manager,"
        "mfi_loan.group_mfi_head_office,mfi_loan.group_mfi_admin",
    )
    mfi_phone_masked = fields.Char("Phone (masked)", compute="_compute_mfi_phone_masked")

    # Applicant
    mfi_alt_phone = fields.Char("Alternate phone number")
    mfi_kra_pin = fields.Char("KRA PIN number")
    mfi_residential_address = fields.Char("Residential address")
    mfi_permanent_address = fields.Char("Permanent address")
    mfi_rural_home = fields.Char("Rural home location")
    mfi_business_type = fields.Char("Business type", help="e.g. Mama mboga, Hardware")
    mfi_business_location = fields.Char("Business location")
    mfi_bank_account_name = fields.Char("Bank account name")
    mfi_bank_account_number = fields.Char("Bank account number")

    # A business's director / contact person
    mfi_contact_name = fields.Char("Director / contact person")
    mfi_contact_id_number = fields.Char("Contact person ID number")
    mfi_contact_phone = fields.Char("Contact person phone")
    mfi_contact_designation = fields.Char("Designation")

    # Financials / business capacity
    mfi_daily_income = fields.Float("Daily income")
    mfi_stock_value = fields.Float("Stock value")
    mfi_stock_turnover = fields.Float("Stock turnover (times)")
    mfi_mpesa_cashflow_6m = fields.Float("M-Pesa cash flow (6 months)")
    mfi_bank_cashflow_6m = fields.Float("Bank cash flow (6 months)")
    mfi_current_loans_count = fields.Integer("Current loans elsewhere")
    mfi_current_loans_value = fields.Float("Value of current loans elsewhere")

    mfi_next_of_kin_ids = fields.One2many("mfi.next.of.kin", "partner_id", "Next of kin")

    mfi_blacklisted = fields.Boolean("Blacklisted", tracking=True)
    mfi_blacklist_reason = fields.Char("Blacklist reason", tracking=True)
    mfi_document_ids = fields.One2many(
        "mfi.client.document", "partner_id", "Documents", domain=[("loan_id", "=", False)]
    )
    mfi_documents_missing = fields.Char("Missing documents", compute="_compute_mfi_documents")
    mfi_documents_complete = fields.Boolean("Documents complete", compute="_compute_mfi_documents")
    mfi_loan_ids = fields.One2many("mfi.loan", "partner_id", "Loans")
    mfi_loan_count = fields.Integer(compute="_compute_mfi_loan_count")
    mfi_loans_taken = fields.Integer("Loans taken", compute="_compute_mfi_borrowing")
    mfi_total_borrowed = fields.Float("Total borrowed", compute="_compute_mfi_borrowing")

    @api.depends("phone")
    def _compute_mfi_phone_masked(self):
        for partner in self:
            partner.mfi_phone_masked = mask_phone(partner.phone)

    @api.depends("mfi_client_type", "mfi_document_ids.kind")
    def _compute_mfi_documents(self):
        for partner in self:
            kinds = set(partner.mfi_document_ids.mapped("kind"))
            missing = []
            if partner.mfi_client_type == "business":
                if "business_registration" not in kinds:
                    missing.append(self.env._("Business registration certificate"))
                if "national_id" not in kinds:
                    missing.append(self.env._("Director / contact person ID"))
            else:
                if "national_id" not in kinds:
                    missing.append(self.env._("National ID"))
                if "passport_photo" not in kinds:
                    missing.append(self.env._("Passport photo"))
            if not kinds & {"mpesa_statement", "bank_statement"}:
                missing.append(self.env._("M-Pesa or bank statement (6 months)"))
            partner.mfi_documents_missing = ", ".join(missing)
            partner.mfi_documents_complete = not missing

    def _compute_mfi_loan_count(self):
        counts = {
            partner.id: count
            for partner, count in self.env["mfi.loan"]._read_group(
                [("partner_id", "in", self.ids)], ["partner_id"], ["__count"]
            )
        }
        for partner in self:
            partner.mfi_loan_count = counts.get(partner.id, 0)

    def _compute_mfi_borrowing(self):
        for partner in self:
            disbursed = partner.mfi_loan_ids.filtered("disbursed_date")
            partner.mfi_loans_taken = len(disbursed)
            partner.mfi_total_borrowed = sum(disbursed.mapped("principal"))

    @api.constrains(*CLIENT_RULE_FIELDS)
    def _check_mfi_client(self):
        for partner in self.sudo():
            if not partner.is_mfi_client:
                continue
            business = partner.mfi_client_type == "business"
            if len((partner.name or "").strip()) < 3:
                raise ValidationError(self.env._("Business name is required.") if business
                                      else self.env._("Full name is required."))
            id_number = (partner.mfi_id_number or "").strip()
            pattern = r"^[A-Za-z0-9/\-]{4,25}$" if business else r"^[A-Za-z0-9]{6,12}$"
            if not re.match(pattern, id_number):
                raise ValidationError(self.env._("Enter the business registration number.") if business
                                      else self.env._("Enter a valid ID number."))
            if business and not (partner.mfi_contact_name or "").strip():
                raise ValidationError(self.env._("Enter the director / contact person."))
            if not (partner.phone or "").strip():
                raise ValidationError(self.env._("A phone number is required: it is used to match M-Pesa payments."))
            if not re.match(r"^\S+@\S+\.\S+$", (partner.email or "").strip()):
                raise ValidationError(self.env._("A valid email address is required."))
            if partner.mfi_kra_pin and not re.match(r"^[AP]\d{9}[A-Z]$", partner.mfi_kra_pin.strip(), re.I):
                raise ValidationError(self.env._("KRA PIN looks like A123456789B."))
            if partner.mfi_date_of_birth and partner.mfi_date_of_birth >= fields.Date.context_today(partner):
                raise ValidationError(self.env._("The date of birth must be in the past."))
            if self.sudo().search_count([
                ("is_mfi_client", "=", True), ("mfi_id_number", "=", id_number), ("id", "!=", partner.id),
            ]):
                raise ValidationError(self.env._("A client with this ID / registration number already exists."))

    def _assign_mfi_client_no(self):
        for partner in self.sudo():
            if partner.is_mfi_client and not partner.mfi_client_no:
                partner.mfi_client_no = self.env["ir.sequence"].next_by_code("mfi.client")

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get("is_mfi_client") for vals in vals_list):
            rules.check(self.env, "clients.write")
        for vals in vals_list:
            if vals.get("is_mfi_client") and any(vals.get(f) for f in NAME_PARTS):
                vals["name"] = compose_name(*(vals.get(f) for f in NAME_PARTS)) or vals.get("name")
            if vals.get("mfi_consent_to_checks"):
                vals.update(mfi_consent_at=fields.Datetime.now(), mfi_consent_by=self.env.uid)
        partners = super().create(vals_list)
        partners._assign_mfi_client_no()
        rules.audit(self.env, "client.created", partners.filtered("is_mfi_client"))
        return partners

    def write(self, vals):
        if {"mfi_blacklisted", "mfi_blacklist_reason"} & vals.keys():
            rules.check(self.env, "clients.blacklist")
            if vals.get("mfi_blacklisted"):
                reason = vals.get("mfi_blacklist_reason")
                if not (reason or "").strip() and not all(p.mfi_blacklist_reason for p in self):
                    raise UserError(self.env._("A reason is required to blacklist a client."))
        locked = LOCKED_AFTER_PUSH & vals.keys()
        if locked and not self.env.context.get("mfi_lending_sync"):
            pushed = self.filtered("mfi_lending_client_id")
            if pushed and any(_differs(partner, f, vals[f]) for partner in pushed for f in locked):
                raise UserError(self.env._(
                    "%(client)s is in the lending service: change these details in its onboarding screen.",
                    client=pushed[0].display_name))
        if vals.get("mfi_consent_to_checks"):
            vals = dict(vals, mfi_consent_at=fields.Datetime.now(), mfi_consent_by=self.env.uid)
        elif "mfi_consent_to_checks" in vals:
            vals = dict(vals, mfi_consent_at=False, mfi_consent_by=False)
        result = super().write(vals)
        if NAME_PARTS & vals.keys():
            for partner in self.filtered(lambda p: p.is_mfi_client and p.mfi_client_type != "business"):
                name = compose_name(partner.mfi_first_name, partner.mfi_middle_name, partner.mfi_last_name)
                if name and name != partner.name:
                    super(ResPartner, partner).write({"name": name})
        if vals.get("is_mfi_client"):
            self._assign_mfi_client_no()
        clients = self.filtered("is_mfi_client")
        if clients and "mfi_blacklisted" in vals:
            action = "client.blacklisted" if vals["mfi_blacklisted"] else "client.blacklist_lifted"
            rules.audit(self.env, action, clients, {"reason": vals.get("mfi_blacklist_reason")})
        changed = sorted(f for f in vals if f in AUDITED_CLIENT_FIELDS)
        if clients and changed:
            labels = [self._fields[f].string for f in changed]
            rules.audit(self.env, "client.updated", clients, {"fields": ", ".join(labels)})
        return result

    def action_view_mfi_loans(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("mfi_loan.action_mfi_loan")
        action["domain"] = [("partner_id", "=", self.id)]
        action["context"] = {"default_partner_id": self.id}
        return action

    def action_new_mfi_loan(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "mfi.loan",
            "view_mode": "form",
            "context": {"default_partner_id": self.id},
        }
