# Copyright 2016 ICTSTUDIO <http://www.ictstudio.eu>
# Copyright 2021 ACSONE SA/NV <https://acsone.eu>
# License: AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
# Port to 20.0 (Dibon): the provider's tokens are never written to the database
# (access-keycloak K15). Odoo's own sign-in compares a one-time secret stored on
# the user (res.users.oauth_access_token) right after the redirect, so that secret
# is a random value, not the provider's token; the access and refresh tokens go
# into the person's session (auth_oidc.session). The PKCE verifier and the nonce
# are the ones made for this session's sign-in, and the nonce is checked.

import logging
import secrets
import time

import requests

from odoo import api, models
from odoo.exceptions import AccessDenied
from odoo.http import request

from .. import session as keys

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = "res.users"

    @staticmethod
    def _auth_oidc_pending(oauth_provider):
        """The verifier and nonce made for this sign-in, if any."""
        if not request:
            return {}
        return (request.session.get(keys.PKCE) or {}).get(str(oauth_provider.id)) or {}

    def _auth_oauth_get_tokens_implicit_flow(self, oauth_provider, params):
        # https://openid.net/specs/openid-connect-core-1_0.html#ImplicitAuthResponse
        return {"access_token": params.get("access_token"), "id_token": params.get("id_token")}

    def _auth_oauth_get_tokens_auth_code_flow(self, oauth_provider, params):
        # https://openid.net/specs/openid-connect-core-1_0.html#AuthResponse
        code = params.get("code")
        # https://openid.net/specs/openid-connect-core-1_0.html#TokenRequest
        auth = None
        if oauth_provider.client_secret:
            auth = (oauth_provider.client_id, oauth_provider.client_secret)
        verifier = self._auth_oidc_pending(oauth_provider).get("verifier") or oauth_provider.code_verifier
        response = requests.post(
            oauth_provider.token_endpoint,
            data=dict(
                client_id=oauth_provider.client_id,
                grant_type="authorization_code",
                code=code,
                code_verifier=verifier,  # PKCE
                redirect_uri=request.httprequest.url_root + "auth_oauth/signin",
            ),
            auth=auth,
            timeout=10,
        )
        response.raise_for_status()
        # https://openid.net/specs/openid-connect-core-1_0.html#TokenResponse
        return response.json()

    @api.model
    def auth_oauth(self, provider, params):
        oauth_provider = self.env["auth.oauth.provider"].browse(provider)
        if oauth_provider.flow == "id_token":
            tokens = self._auth_oauth_get_tokens_implicit_flow(oauth_provider, params)
        elif oauth_provider.flow == "id_token_code":
            tokens = self._auth_oauth_get_tokens_auth_code_flow(oauth_provider, params)
        else:
            return super().auth_oauth(provider, params)
        access_token, id_token = tokens.get("access_token"), tokens.get("id_token")
        if not access_token:
            _logger.error("No access_token in response.")
            raise AccessDenied()
        if not id_token:
            _logger.error("No id_token in response.")
            raise AccessDenied()
        validation = oauth_provider._parse_id_token(id_token, access_token)
        expected_nonce = self._auth_oidc_pending(oauth_provider).get("nonce")
        if expected_nonce and validation.get("nonce") != expected_nonce:
            _logger.error("The id_token's nonce does not match this sign-in.")
            raise AccessDenied()
        # required check
        if "sub" in validation and "user_id" not in validation:
            # set user_id for auth_oauth, user_id is not an OpenID Connect standard
            # claim:
            # https://openid.net/specs/openid-connect-core-1_0.html#StandardClaims
            validation["user_id"] = validation["sub"]
        elif not validation.get("user_id"):
            _logger.error("user_id claim not found in id_token (after mapping).")
            raise AccessDenied()
        # retrieve and sign in user, with a one-time secret in place of the token
        secret = secrets.token_urlsafe(32)
        params["access_token"] = secret
        login = self._auth_oauth_signin(provider, validation, params)
        if not login:
            raise AccessDenied()
        if request:
            # moved into the session by the signin route, once the person is signed in
            request._auth_oidc_tokens = {
                keys.ACCESS_TOKEN: access_token,
                keys.REFRESH_TOKEN: tokens.get("refresh_token"),
                keys.EXPIRES_AT: time.time() + int(tokens.get("expires_in") or 300),
                keys.PROVIDER: oauth_provider.id,
            }
        # return user credentials
        return (self.env.cr.dbname, login, secret)
