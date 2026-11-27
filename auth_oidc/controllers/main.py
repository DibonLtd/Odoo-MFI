# Copyright 2016 ICTSTUDIO <http://www.ictstudio.eu>
# Copyright 2021 ACSONE SA/NV <https://acsone.eu>
# License: AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
# Port to 20.0 (Dibon): urllib instead of werkzeug.urls (gone in Werkzeug 3); PKCE
# verifier and nonce new for each sign-in and kept in the session (they were one
# fixed verifier per provider, and the nonce was never checked); after sign-in the
# provider's tokens go into the session only.

import base64
import hashlib
import logging
import secrets
from urllib.parse import parse_qsl, urlencode

from odoo.http import request, route

from odoo.addons.auth_oauth.controllers.main import OAuthController, OAuthLogin

from .. import session as keys

_logger = logging.getLogger(__name__)


class OpenIDLogin(OAuthLogin):
    def list_providers(self):
        providers = super().list_providers()
        pending = {}
        for provider in providers:
            flow = provider.get("flow")
            if flow in ("id_token", "id_token_code"):
                params = dict(parse_qsl(provider["auth_link"].split("?", 1)[-1]))
                verifier = secrets.token_urlsafe(48)
                nonce = secrets.token_urlsafe()
                pending[str(provider["id"])] = {"verifier": verifier, "nonce": nonce}
                params["nonce"] = nonce
                # response_type
                if flow == "id_token":
                    # https://openid.net/specs/openid-connect-core-1_0.html
                    # #ImplicitAuthRequest
                    params["response_type"] = "id_token token"
                elif flow == "id_token_code":
                    # https://openid.net/specs/openid-connect-core-1_0.html#AuthRequest
                    params["response_type"] = "code"
                # PKCE (https://tools.ietf.org/html/rfc7636)
                params["code_challenge"] = base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode("ascii")).digest()
                ).rstrip(b"=").decode("ascii")
                params["code_challenge_method"] = "S256"
                # scope
                if provider.get("scope"):
                    if "openid" not in provider["scope"].split():
                        _logger.error("openid connect scope must contain 'openid'")
                    params["scope"] = provider["scope"]
                # auth link that the user will click
                provider["auth_link"] = "{}?{}".format(
                    provider["auth_endpoint"], urlencode(params)
                )
            # never handed to the login page
            provider.pop("client_secret", None)
            provider.pop("code_verifier", None)
        if pending and request:
            request.session[keys.PKCE] = pending
        return providers


class OpenIDController(OAuthController):
    @route()
    def signin(self, **kw):
        response = super().signin(**kw)
        tokens = getattr(request, "_auth_oidc_tokens", None)
        if tokens and request.session.uid:
            request.session.update(tokens)
        request.session.pop(keys.PKCE, None)
        return response
