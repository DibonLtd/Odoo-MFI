"""The client's link to the Kapu lending service: the push, and what the
onboarding screen asks for. The work is in services/lending.py."""

from odoo import api, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.mfi_lending_api.services import LendingClient, LendingError

from ..services.lending import Onboarding, decode_upload, failure, local_failure
from . import rules

SCREEN_COMMANDS = ("update_contact", "send_phone_code", "confirm_phone", "send_upload_link", "submit",
                   "upload_file", "verifications")


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------------------------------------------------
    # Push: one client (form button) or several (list action and dialog)
    # ------------------------------------------------------------------

    def action_mfi_lending_push(self):
        """Form button: create this client in the lending service."""
        self.ensure_one()
        rules.check(self.env, "lending.push")
        result = Onboarding(self).push()
        if not result["ok"]:
            # Commit what was done (a created client's id) before showing why it stopped.
            return self._mfi_lending_notify(result["error"]["message"], "danger", sticky=True)
        message = self.env._("Created in the lending service. Next: confirm the phone, then submit.")
        if result.get("skipped"):
            message += " " + " ".join(result["skipped"])
        return self._mfi_lending_notify(message, "success", next_action=self.action_mfi_lending_open())

    def mfi_lending_push(self):
        """One client of a bulk push: called by the dialog, once per client, in the
        person's own request (DECISIONS D-011). Never raises: returns the outcome."""
        self.ensure_one()
        if not rules.allowed(self.env, "lending.push"):
            return local_failure(self.env._("You do not have permission to do this."))
        return dict(Onboarding(self).push(), id=self.id, name=self.display_name,
                    clientNo=self.mfi_client_no)

    @api.model
    def action_mfi_lending_push_selected(self):
        """List action: open the dialog for the selected clients."""
        rules.check(self.env, "lending.push")
        ids = self.env.context.get("active_ids") or []
        clients = self.browse(ids).filtered("is_mfi_client")
        if not clients:
            raise UserError(self.env._("Select the clients to create in the lending service."))
        return {
            "type": "ir.actions.client",
            "tag": "mfi_loan.lending_push",
            "name": self.env._("Create in the lending service"),
            "target": "new",
            "params": {"ids": clients.ids},
        }

    def _mfi_lending_notify(self, message, kind, sticky=False, next_action=None):
        params = {"type": kind, "message": message, "sticky": sticky}
        params["next"] = next_action or {"type": "ir.actions.client", "tag": "soft_reload"}
        return {"type": "ir.actions.client", "tag": "display_notification", "params": params}

    # ------------------------------------------------------------------
    # The onboarding screen
    # ------------------------------------------------------------------

    def action_mfi_lending_open(self):
        self.ensure_one()
        if not self.mfi_lending_client_id:
            raise UserError(self.env._("Create the client in the lending service first."))
        return {
            "type": "ir.actions.client",
            "tag": "mfi_loan.lending_onboarding",
            "name": self.env._("Onboarding: %s", self.display_name),
            "params": {"partner_id": self.id},
        }

    def _mfi_lending_check_reader(self):
        """Every Microfinance role may read the lending service's clients (masked)."""
        if not (self.env.su or self.env.user.has_group("mfi_loan.group_mfi_user")):
            raise AccessError(self.env._("You do not have permission to do this."))

    def mfi_lending_read(self):
        """Everything the screen shows, live from the service, masked by it."""
        self.ensure_one()
        self._mfi_lending_check_reader()
        self.check_access("read")
        base = {"partner": {"id": self.id, "name": self.display_name, "clientNo": self.mfi_client_no,
                            "canAct": rules.allowed(self.env, "lending.push")}}
        if not self.mfi_lending_client_id:
            return dict(local_failure(self.env._("This client is only in Odoo.")), **base)
        return dict(Onboarding(self).read(), **base)

    def mfi_lending_command(self, command, params=None):
        """One command from the screen. Never raises for a refusal: returns it."""
        self.ensure_one()
        self._mfi_lending_check_reader()
        self.check_access("read")
        if command not in SCREEN_COMMANDS:
            raise UserError(self.env._("Unknown command."))
        if not self.mfi_lending_client_id:
            return local_failure(self.env._("Create the client in the lending service first."))
        params = params or {}
        onboarding = Onboarding(self)
        if command == "update_contact":
            return onboarding.update_contact(params.get("values") or {})
        if command == "confirm_phone":
            return onboarding.confirm_phone(params.get("code"))
        if command == "send_upload_link":
            return onboarding.send_upload_link(params.get("documentTypes"), params.get("channel"))
        if command == "upload_file":
            try:
                content = decode_upload(params.get("data"))
            except ValueError:
                return local_failure(self.env._("The file could not be read."))
            return onboarding.upload_file(params.get("documentType"), content, params.get("contentType"))
        if command == "verifications":
            return onboarding.verifications()
        return getattr(onboarding, command)()

    @api.model
    def mfi_lending_list(self, state=None, cursor=None, limit=50):
        """The lending service's clients, live, with the Odoo client each is linked to."""
        self._mfi_lending_check_reader()
        try:
            page = LendingClient.for_request(self.env).list_clients(
                limit=min(int(limit or 50), 200), cursor=cursor or None, state=state or None).data
        except LendingError as error:
            return failure(self.env, error)
        ids = [item["id"] for item in page.get("items") or []]
        linked = {p.mfi_lending_client_id: {"id": p.id, "clientNo": p.mfi_client_no}
                  for p in self.search([("mfi_lending_client_id", "in", ids)])}
        for item in page.get("items") or []:
            item["odoo"] = linked.get(item["id"])
        return {"ok": True, "page": page}
