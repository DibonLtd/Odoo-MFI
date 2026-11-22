"""Step-by-step guides: a green "What to do here" box on each Microfinance page,
and a "Next step" box on the loan form that follows the loan along.

Ported from the Dibon Events guides (dibon_event, dbe.guide) to Odoo 19.
"""
from markupsafe import Markup, escape

from odoo import api, fields, models, tools

from .rules import APPROVAL_CHAIN

VIEW_TYPES = [
    ("list", "List"),
    ("kanban", "Kanban"),
    ("form", "Form"),
    ("calendar", "Calendar"),
    ("pivot", "Pivot"),
    ("graph", "Graph"),
    ("activity", "Activity"),
]
SHOW_GUIDES_PARAM = "mfi_loan.show_guides"
# Next step box: tone -> (Bootstrap alert class, Font Awesome icon)
NEXT_STEP_TONES = {
    "info": ("alert-info", "fa-flag"),
    "success": ("alert-success", "fa-check-circle"),
    "warning": ("alert-warning", "fa-hourglass-half"),
    "danger": ("alert-danger", "fa-exclamation-triangle"),
    "muted": ("alert-secondary", "fa-flag-checkered"),
}


def guides_enabled(env):
    """On unless an administrator switched them off in Settings."""
    return env["ir.config_parameter"].sudo().get_param(SHOW_GUIDES_PARAM, "True") != "False"


class MfiGuide(models.Model):
    """One page's guide. It matches a model, optionally narrowed to one view type
    and/or one window action (the most specific match wins). The help text lives
    here, not in the view XML, so managers can edit it."""

    _name = "mfi.guide"
    _description = "Page guide"
    _order = "sequence, id"

    name = fields.Char("Reference", required=True, help='Internal name, e.g. "Loans: list".')
    model = fields.Char("Model", required=True, index=True, help="Technical model name, e.g. mfi.loan")
    view_type = fields.Selection(VIEW_TYPES, string="View", help="Leave empty for every view of the model.")
    action_xmlid = fields.Char(
        "Menu action", help="External ID of a window action, to show the guide on that menu only.")
    title = fields.Char(required=True, translate=True)
    body = fields.Html("What to do here", translate=True, sanitize=True)
    button_ids = fields.One2many("mfi.guide.button", "guide_id", string="Buttons", copy=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    @api.model
    def mfi_get_guides(self):
        """Every guide the current user should see; the browser matches them to
        pages itself (one call per session)."""
        if not guides_enabled(self.env):
            return []
        hidden = set(self.env.user.sudo().mfi_guide_hidden_ids.ids)
        return [guide for guide in self._mfi_guides_data() if guide["id"] not in hidden]

    @api.model
    @tools.ormcache("self.env.lang")
    def _mfi_guides_data(self):
        result = []
        for guide in self.sudo().search([]):
            buttons = [
                {"label": button.label, "action_id": action_id}
                for button in guide.button_ids
                for action_id in [guide._mfi_action_id(button.action_xmlid)]
                if action_id
            ]
            result.append({
                "id": guide.id,
                "model": guide.model,
                "view_type": guide.view_type or False,
                "action_id": guide._mfi_action_id(guide.action_xmlid),
                "title": guide.title,
                "body": guide.body or "",
                "sequence": guide.sequence,
                "buttons": buttons,
            })
        return result

    def _mfi_action_id(self, xmlid):
        action = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else None
        return action.id if action else False

    # The guide list is cached per language: any change clears it.
    @api.model_create_multi
    def create(self, vals_list):
        self.env.registry.clear_cache()
        return super().create(vals_list)

    def write(self, vals):
        self.env.registry.clear_cache()
        return super().write(vals)

    def unlink(self):
        self.env.registry.clear_cache()
        return super().unlink()


class MfiGuideButton(models.Model):
    _name = "mfi.guide.button"
    _description = "Page guide button"
    _order = "sequence, id"

    guide_id = fields.Many2one("mfi.guide", required=True, ondelete="cascade", index=True)
    label = fields.Char(required=True, translate=True)
    action_xmlid = fields.Char("Action", required=True, help="External ID of the action the button opens.")
    sequence = fields.Integer(default=10)

    @api.model_create_multi
    def create(self, vals_list):
        self.env.registry.clear_cache()
        return super().create(vals_list)

    def write(self, vals):
        self.env.registry.clear_cache()
        return super().write(vals)

    def unlink(self):
        self.env.registry.clear_cache()
        return super().unlink()


class ResUsers(models.Model):
    _inherit = "res.users"

    mfi_guide_hidden_ids = fields.Many2many(
        "mfi.guide", "mfi_guide_hidden_user_rel", "user_id", "guide_id", string="Closed page guides")

    @api.model
    def mfi_hide_guide(self, guide_id):
        """The current user closes one guide."""
        self.env.user.sudo().mfi_guide_hidden_ids = [fields.Command.link(int(guide_id))]
        return True

    def action_mfi_reset_guides(self):
        """The current user brings every closed guide back."""
        self.env.user.sudo().mfi_guide_hidden_ids = [fields.Command.clear()]
        return {"type": "ir.actions.client", "tag": "reload"}


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mfi_show_guides = fields.Boolean(
        "Page guides", help='Show a green "What to do here" box at the top of each Microfinance page.')

    def get_values(self):
        res = super().get_values()
        res["mfi_show_guides"] = guides_enabled(self.env)
        return res

    def set_values(self):
        super().set_values()
        # Stored as text: a boolean config_parameter deletes the key when off,
        # which would read back as the default (on).
        self.env["ir.config_parameter"].sudo().set_param(
            SHOW_GUIDES_PARAM, "True" if self.mfi_show_guides else "False")


class MfiLoan(models.Model):
    _inherit = "mfi.loan"

    next_step_title = fields.Char("Next step", compute="_compute_next_step")
    next_step_html = fields.Html("Next step details", compute="_compute_next_step", sanitize=False)
    next_step_tone = fields.Selection(
        [("info", "Info"), ("success", "Success"), ("warning", "Warning"), ("danger", "Danger"), ("muted", "Done")],
        compute="_compute_next_step")

    @api.depends("state", "approval_stage", "health", "awaiting_me", "agreement_generated_at",
                 "agreement_sent_at", "document_ids", "upfront_fee_ref", "house_visit_date")
    @api.depends_context("uid")  # "your decision" depends on who is looking
    def _compute_next_step(self):
        enabled = guides_enabled(self.env)
        for loan in self:
            if not enabled:
                loan.next_step_title = loan.next_step_html = loan.next_step_tone = False
                continue
            title, steps, tone = loan._mfi_next_step()
            loan.next_step_title = title
            loan.next_step_tone = tone
            loan.next_step_html = loan._mfi_next_step_box(title, steps, tone)

    @staticmethod
    def _mfi_next_step_box(title, steps, tone):
        alert, icon = NEXT_STEP_TONES[tone]
        items = Markup("").join(Markup("<li>%s</li>") % step for step in steps)
        return Markup(
            '<div class="alert %s o_mfi_next_step d-flex gap-3 align-items-start py-2 mb-3" role="status">'
            '<i class="fa %s fs-4 mt-1" aria-hidden="true"></i>'
            '<div class="flex-grow-1"><div class="fw-bold">%s</div>%s</div></div>'
        ) % (alert, icon, title, Markup('<ol class="small mb-0">%s</ol>') % items if steps else "")

    def _mfi_next_step(self):
        """(title, [steps], tone) for the loan's current state, in plain words."""
        self.ensure_one()
        _ = self.env._
        b = lambda text: Markup("<b>%s</b>") % text  # noqa: E731
        state = self.state
        if not self.id and state == "draft":
            return (_("Step 1 of 5: capture the application"),
                    [_("Pick the client, the loan type, the amount and the term."),
                     _("Fill in the guarantor and the security details, then save.")], "info")
        if state == "draft":
            problems = self._application_problems()
            steps = [escape(p) for p in problems] or [_("Everything is filled in.")]
            steps.append(Markup(_("Click %s.")) % b(_("Send to officer")))
            return _("Step 1 of 5: send the application to the officer"), steps, "info"
        if state == "pending_information":
            outstanding = self._checklist_problems()
            steps = []
            if not self.agreement_generated_at:
                steps.append(Markup(_("Click %s and have the client sign it.")) % b(_("Generate agreement")))
            if outstanding:
                steps.append(_("Still outstanding: %s.", ", ".join(outstanding)))
            if self.upfront_total > 0 and not (self.upfront_fee_ref or "").strip():
                steps.append(_("Record the payment reference for the upfront fees (KES %s).",
                               f"{self.upfront_total:,.0f}"))
            steps.append(Markup(_("Click %s.")) % b(_("Send for approval")))
            return _("Step 2 of 5: complete the checklist"), steps, "info"
        if state == "pending_approval":
            stage = self.approval_stage
            group = self.env.ref(APPROVAL_CHAIN[stage - 1], raise_if_not_found=False) \
                if 1 <= stage <= len(APPROVAL_CHAIN) else None
            who = group.name if group else _("the approver")
            if self.awaiting_me:
                return (_("Step 3 of 5: your decision (stage %(stage)s of %(total)s)",
                          stage=stage, total=len(APPROVAL_CHAIN)),
                        [_("Review the client, the documents and the house visit."),
                         Markup(_("Click %(approve)s, or %(reject)s with a reason.")) % {
                             "approve": b(_("Approve stage")), "reject": b(_("Reject"))}],
                        "warning")
            return (_("Step 3 of 5: waiting for approval (stage %(stage)s of %(total)s)",
                      stage=stage, total=len(APPROVAL_CHAIN)),
                    [_("Waiting for: %s. Each stage needs a different person, "
                       "and not the one who created the application.", who)],
                    "warning")
        if state == "approved":
            return (_("Step 4 of 5: disburse the loan"),
                    [Markup(_("Finance clicks %s and types the M-Pesa or bank reference.")) % b(_("Disburse")),
                     _("The repayment schedule starts from the disbursement date.")],
                    "success")
        if state == "active":
            if self.health in ("arrears", "overdue"):
                return (_("Step 5 of 5: recover the missed instalments"),
                        [_("Call or visit the client and log it in the Collections tab."),
                         _("Send a reminder SMS or WhatsApp, or record a promise to pay."),
                         Markup(_("When money comes in, click %s.")) % b(_("Record payment"))],
                        "danger")
            return (_("Step 5 of 5: collect the repayments"),
                    [Markup(_("Record each repayment with %s; it clears default interest first, then the instalments in order."))
                     % b(_("Record payment")),
                     Markup(_("The client can close the loan early with %s.")) % b(_("Early settlement"))],
                    "success")
        if state == "rejected":
            return (_("Rejected"),
                    [Markup(_("Fix what the approver asked for, then click %s to start again.")) % b(_("Reopen"))],
                    "muted")
        if state == "repaid":
            return _("Done: this loan is fully repaid"), [], "muted"
        return _("Closed: this loan was written off"), [], "muted"
