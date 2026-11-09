from odoo import api, fields, models
from odoo.exceptions import UserError

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


class MfiClientDocument(models.Model):
    _name = "mfi.client.document"
    _description = "Client or loan document"
    _order = "id desc"

    partner_id = fields.Many2one("res.partner", "Client", required=True, ondelete="cascade", index=True)
    loan_id = fields.Many2one("mfi.loan", ondelete="cascade", index=True,
                              help="Set for a document that belongs to one application.")
    kind = fields.Selection(CLIENT_DOCUMENT_KINDS + LOAN_DOCUMENT_KINDS, required=True)
    file = fields.Binary(attachment=True, required=True)
    file_name = fields.Char()
    note = fields.Char()

    @api.model_create_multi
    def create(self, vals_list):
        rules.check(self.env, "clients.write")
        for vals in vals_list:
            if vals.get("loan_id") and not vals.get("partner_id"):
                vals["partner_id"] = self.env["mfi.loan"].browse(vals["loan_id"]).partner_id.id
        return super().create(vals_list)


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_mfi_client = fields.Boolean("Microfinance client")
    mfi_client_type = fields.Selection(
        [("individual", "Individual"), ("business", "Business")],
        "Client type", default="individual",
    )
    mfi_id_number = fields.Char(
        "ID / registration number",
        groups="mfi_loan.group_mfi_loan_officer,mfi_loan.group_mfi_credit_manager,"
        "mfi_loan.group_mfi_head_office,mfi_loan.group_mfi_admin",
    )
    mfi_blacklisted = fields.Boolean("Blacklisted", tracking=True)
    mfi_blacklist_reason = fields.Char("Blacklist reason", tracking=True)
    mfi_document_ids = fields.One2many(
        "mfi.client.document", "partner_id", "Documents", domain=[("loan_id", "=", False)]
    )
    mfi_documents_missing = fields.Char("Missing documents", compute="_compute_mfi_documents")
    mfi_documents_complete = fields.Boolean("Documents complete", compute="_compute_mfi_documents")
    mfi_loan_ids = fields.One2many("mfi.loan", "partner_id", "Loans")
    mfi_loan_count = fields.Integer(compute="_compute_mfi_loan_count")

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

    def write(self, vals):
        if {"mfi_blacklisted", "mfi_blacklist_reason"} & vals.keys():
            rules.check(self.env, "clients.blacklist")
            if vals.get("mfi_blacklisted"):
                reason = vals.get("mfi_blacklist_reason")
                if not (reason or "").strip() and not all(p.mfi_blacklist_reason for p in self):
                    raise UserError(self.env._("A reason is required to blacklist a client."))
        return super().write(vals)

    def action_view_mfi_loans(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("mfi_loan.action_mfi_loan")
        action["domain"] = [("partner_id", "=", self.id)]
        action["context"] = {"default_partner_id": self.id}
        return action
