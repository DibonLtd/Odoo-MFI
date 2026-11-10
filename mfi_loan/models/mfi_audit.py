"""The audit log, sign-in events and session limits.

The portal records every sign-in, approval, disbursement, payment, settings
change and view of a client's personal details in one log that Super Admin,
CEO, Head Office and the Auditor can search. Each record's chatter keeps its
own history as well; this log is the single place to look across them.
"""

import logging
import time

from odoo import api, fields, models
from odoo.exceptions import AccessDenied, UserError
from odoo.http import request

from . import rules

_logger = logging.getLogger(__name__)

# Requests the web client makes on its own; they do not count as activity.
BACKGROUND_PATHS = ("/websocket", "/longpolling", "/bus/", "/web/webclient/version_info",
                    "/mail/data", "/web/session/get_session_info")


def _ip():
    try:
        return request.httprequest.remote_addr if request else False
    except RuntimeError:  # no request bound to this thread
        return False


class MfiAuditLog(models.Model):
    _name = "mfi.audit.log"
    _description = "Microfinance audit log"
    _order = "date desc, id desc"
    _rec_name = "action"

    date = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True, index=True)
    user_id = fields.Many2one("res.users", "User", readonly=True, ondelete="set null", index=True)
    user_login = fields.Char("User email", readonly=True)
    action = fields.Char(required=True, readonly=True, index=True,
                         help="What happened, e.g. loan.approved, payment.reversed, pii.viewed.")
    entity = fields.Char("Record type", readonly=True)
    res_model = fields.Char(readonly=True, index=True)
    res_id = fields.Integer(readonly=True, index=True)
    res_name = fields.Char("Record", readonly=True)
    detail = fields.Text(readonly=True)
    ip = fields.Char("IP address", readonly=True)

    @api.model
    def _log(self, action, records=None, detail=None, user=None):
        user = user or self.env.user
        if isinstance(detail, dict):
            detail = "; ".join(f"{key}: {value}" for key, value in detail.items() if value not in (None, False, ""))
        base = {
            "action": action,
            "user_id": user.id or False,
            "user_login": user.login or False,
            "detail": detail or False,
            "ip": _ip(),
        }
        if not records:
            return self.sudo().create([base])
        return self.sudo().create([{
            **base,
            "entity": record._description,
            "res_model": record._name,
            "res_id": record.id,
            "res_name": record.display_name,
        } for record in records])

    @api.model
    def _log_committed(self, action, records=None, detail=None, user=None):
        """Log in a transaction of its own, for events whose request is rolled back
        (a refused password, a failed sign-in). Records must exist already."""
        user = user or self.env.user
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, api.SUPERUSER_ID, {})
                env["mfi.audit.log"]._log(action, records and records.with_env(env), detail,
                                          user=user.with_env(env))
        except Exception:  # never let the log change the outcome
            _logger.warning("Could not record %s in the audit log", action, exc_info=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(self.env._("The audit log is written by the system only."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(self.env._("Audit log entries cannot be changed."))

    def unlink(self):
        if not (self.env.su and self.env.context.get("mfi_audit_purge")):
            raise UserError(self.env._("Audit log entries cannot be deleted."))
        return super().unlink()

    def action_open_record(self):
        self.ensure_one()
        if not (self.res_model in self.env and self.res_id):
            raise UserError(self.env._("This entry is not about a single record."))
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(self.env._("The record no longer exists."))
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
            "views": [(False, "form")],
        }


class ResUsers(models.Model):
    _inherit = "res.users"

    def _update_last_login(self):
        super()._update_last_login()
        for user in self:
            if user.sudo().has_group("mfi_loan.group_mfi_user"):
                self.env["mfi.audit.log"].sudo()._log("login", user, user=user)

    def _login(self, credential, user_agent_env):
        try:
            return super()._login(credential, user_agent_env)
        except AccessDenied:
            self._mfi_log_failed_login(credential.get("login"))
            raise

    @api.model
    def _mfi_log_failed_login(self, login):
        """Record a failed sign-in for a Microfinance user. The request's own
        transaction is rolled back on failure, so this uses a cursor of its own."""
        if not login:
            return
        user = self.sudo().search(self._get_login_domain(login), limit=1)
        if user and user.has_group("mfi_loan.group_mfi_user"):
            self.env["mfi.audit.log"].sudo()._log_committed("login.failed", user, user=user)


class IrHttp(models.AbstractModel):
    """Session limits from Microfinance settings: sign out after a period of
    inactivity, and after a maximum session length, as the portal does."""

    _inherit = "ir.http"

    @classmethod
    def _authenticate_explicit(cls, auth):
        if request.session.uid:
            cls._mfi_enforce_session_limits()
        return super()._authenticate_explicit(auth)

    @classmethod
    def _mfi_enforce_session_limits(cls):
        session = request.session
        params = request.env["ir.config_parameter"].sudo()
        try:
            idle = int(params.get_param("mfi_loan.session_idle_minutes") or 0)
            hours = int(params.get_param("mfi_loan.session_max_hours") or 0)
        except ValueError:
            return
        if not (idle or hours):
            return
        now = time.time()
        started, seen = session.get("mfi_started"), session.get("mfi_seen")
        expired = (idle and seen and now - seen > idle * 60) or (hours and started and now - started > hours * 3600)
        if expired:
            session.logout(keep_db=True)
            request.env = api.Environment(request.env.cr, None, session.context)
            return
        if not started:
            session["mfi_started"] = now
        background = request.httprequest.path.startswith(BACKGROUND_PATHS)
        if not background and (not seen or now - seen > 60):
            session["mfi_seen"] = now
