from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services.auth import clear_cached_tokens
from ..services.client import LendingClient
from ..services.config import AUTH_MODES, DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT, PREFIX
from ..services.errors import LendingError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mfi_lending_enabled = fields.Boolean("Connect to the lending service", config_parameter=PREFIX + "enabled")
    mfi_lending_base_url = fields.Char("Service address", config_parameter=PREFIX + "base_url",
                                       help="For example https://lending.roan.example or, for the stub, http://localhost:8094")
    mfi_lending_auth_mode = fields.Selection(AUTH_MODES, "Sign-in", default="static",
                                             config_parameter=PREFIX + "auth_mode")
    mfi_lending_token_url = fields.Char("Keycloak token address", config_parameter=PREFIX + "token_url",
                                        help=".../realms/staff/protocol/openid-connect/token")
    mfi_lending_client_id = fields.Char("Keycloak client", config_parameter=PREFIX + "client_id")
    mfi_lending_audience = fields.Char("Audience", default="lending-service", config_parameter=PREFIX + "audience")
    mfi_lending_connect_timeout = fields.Integer("Connect timeout (s)", default=DEFAULT_CONNECT_TIMEOUT,
                                                 config_parameter=PREFIX + "connect_timeout")
    mfi_lending_read_timeout = fields.Integer("Read timeout (s)", default=DEFAULT_READ_TIMEOUT,
                                              config_parameter=PREFIX + "read_timeout")
    mfi_lending_upload_hosts = fields.Char("Document upload hosts", config_parameter=PREFIX + "upload_hosts",
                                           help="Hosts the service's upload addresses may point to, separated by commas. Files go nowhere else.")
    mfi_lending_stub_example = fields.Char("Stub example", config_parameter=PREFIX + "stub_example",
                                           help="Static sign-in only: sent as X-Stub-Example, to get one of the stub's named answers.")
    mfi_lending_skip_upload_transfer = fields.Boolean("Skip the file transfer (stub only)",
                                                      config_parameter=PREFIX + "skip_upload_transfer")

    def set_values(self):
        super().set_values()
        clear_cached_tokens()

    def action_mfi_lending_test(self):
        self.ensure_one()
        self.execute()
        try:
            LendingClient.for_request(self.env).list_clients(limit=1)
        except LendingError as error:
            raise UserError(error.message(self.env)) from None
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"type": "success", "message": self.env._("The lending service answered.")},
        }

    @api.model
    def _mfi_lending_secret_names(self):
        """The secrets live outside the database: shown so administrators know where."""
        return ["kapu_lending_client_secret", "kapu_lending_static_token"]
