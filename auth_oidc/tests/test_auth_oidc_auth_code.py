# Copyright 2021 ACSONE SA/NV <https://acsone.eu>
# License: AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import contextlib
import json
import logging
from urllib.parse import parse_qs, urlparse

import responses
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose.exceptions import JWTError
from jose.utils import long_to_base64

import odoo
from odoo.exceptions import AccessDenied
from odoo.tests import common

from .. import session as keys

from odoo.addons.http_routing.tests.common import MockRequest as _MockRequest

from ..controllers.main import OpenIDLogin

BASE_URL = f"http://localhost:{odoo.tools.config['http_port']}"


@contextlib.contextmanager
def MockRequest(env):
    with _MockRequest(env) as request:
        request.httprequest.url_root = BASE_URL + "/"
        request.params = {}
        yield request


class TestAuthOIDCAuthorizationCodeFlow(common.HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        (
            cls.rsa_key_pem,
            cls.rsa_key_public_pem,
            cls.rsa_key_public_jwk,
        ) = cls._generate_key()
        _, cls.second_key_public_pem, _ = cls._generate_key()

    @staticmethod
    def _generate_key():
        rsa_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )
        rsa_key_pem = rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode("utf8")
        rsa_key_public = rsa_key.public_key()
        rsa_key_public_pem = rsa_key_public.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf8")
        jwk = {
            # https://datatracker.ietf.org/doc/html/rfc7518#section-6.1
            "kty": "RSA",
            "use": "sig",
            "n": long_to_base64(rsa_key_public.public_numbers().n).decode("utf-8"),
            "e": long_to_base64(rsa_key_public.public_numbers().e).decode("utf-8"),
        }
        return rsa_key_pem, rsa_key_public_pem, jwk

    def setUp(self):
        super().setUp()
        # set up our test provider to bind the test user to it
        self.provider_rec = self.env["auth.oauth.provider"].create(
            {
                "name": "OAuth Provider for TestAuthOIDCAuthorizationCodeFlow",
                "client_id": "auth_oidc-test",
                "enabled": True,
                "body": "Config of an oauth provider for tests",
                "scope": "openid email",
                "flow": "id_token_code",
                "auth_endpoint": "http://localhost:8080/auth/realms/master/protocol/openid-connect/auth",
                "token_endpoint": "http://localhost:8080/auth/realms/master/protocol/openid-connect/token",
                "jwks_uri": "http://localhost:8080/auth/realms/master/protocol/openid-connect/certs",
            }
        )
        self.assertEqual(len(self.provider_rec), 1)

    def test_auth_link(self):
        """Test that the authentication link is correct."""
        # disable existing providers except our test provider
        self.env["auth.oauth.provider"].search(
            [("client_id", "!=", "auth_oidc-test")]
        ).write(dict(enabled=False))
        with MockRequest(self.env):
            providers = OpenIDLogin().list_providers()
            self.assertEqual(len(providers), 1)
            auth_link = providers[0]["auth_link"]
            assert auth_link.startswith(self.provider_rec.auth_endpoint)
            params = parse_qs(urlparse(auth_link).query)
            self.assertEqual(params["response_type"], ["code"])
            self.assertEqual(params["client_id"], [self.provider_rec.client_id])
            self.assertEqual(params["scope"], ["openid email"])
            self.assertTrue(params["code_challenge"])
            self.assertEqual(params["code_challenge_method"], ["S256"])
            self.assertTrue(params["nonce"])
            self.assertTrue(params["state"])
            self.assertEqual(params["redirect_uri"], [BASE_URL + "/auth_oauth/signin"])

    def _assert_token_kept_out(self, user, credential, provider_token):
        """Dibon port: the provider's token is never stored on the user (K15)."""
        self.assertNotEqual(credential, provider_token)
        stored = user.sudo().oauth_access_token
        self.assertEqual(stored, credential)  # the one-time sign-in secret
        self.assertNotEqual(stored, provider_token)

    def _prepare_login_test_user(self):
        user = self.env["res.users"].create(
            {
                "login": "auth_oidc_test_user",
                "name": "Auth OIDC Test User",
            }
        )
        user.write({"oauth_provider_id": self.provider_rec.id, "oauth_uid": user.login})
        return user

    def _prepare_login_test_responses(
        self, access_token="42", id_token_body=None, id_token_headers=None, keys=None
    ):
        if id_token_body is None:
            id_token_body = {}
        if id_token_headers is None:
            id_token_headers = {"kid": "the_key_id"}
        responses.add(
            responses.POST,
            "http://localhost:8080/auth/realms/master/protocol/openid-connect/token",
            json={
                "access_token": access_token,
                "id_token": jwt.encode(
                    id_token_body,
                    self.rsa_key_pem,
                    algorithm="RS256",
                    headers=id_token_headers,
                ),
            },
        )
        if keys is None:
            if "kid" in id_token_headers:
                keys = [{"kid": "the_key_id", "keys": [self.rsa_key_public_pem]}]
            else:
                keys = [{"keys": [self.rsa_key_public_pem]}]
        responses.add(
            responses.GET,
            "http://localhost:8080/auth/realms/master/protocol/openid-connect/certs",
            json={"keys": keys},
        )

    @responses.activate
    def test_login(self):
        """Test that login works"""
        user = self._prepare_login_test_user()
        self._prepare_login_test_responses(id_token_body={"user_id": user.login})

        params = {"state": json.dumps({})}
        with MockRequest(self.env):
            db, login, token = self.env["res.users"].auth_oauth(
                self.provider_rec.id,
                params,
            )
        self._assert_token_kept_out(user, token, "42")
        self.assertEqual(login, user.login)

    @responses.activate
    def test_login_without_kid(self):
        """Test that login works when ID Token has no kid in header"""
        user = self._prepare_login_test_user()
        self._prepare_login_test_responses(
            id_token_body={"user_id": user.login},
            id_token_headers={},
            access_token=chr(42),
        )

        params = {"state": json.dumps({})}
        with MockRequest(self.env):
            db, login, token = self.env["res.users"].auth_oauth(
                self.provider_rec.id,
                params,
            )
        self._assert_token_kept_out(user, token, "*")
        self.assertEqual(login, user.login)

    @responses.activate
    def test_login_with_sub_claim(self):
        """Test that login works when ID Token contains only standard claims"""
        self.provider_rec.token_map = False
        user = self._prepare_login_test_user()
        self._prepare_login_test_responses(
            id_token_body={"sub": user.login}, access_token="1764"
        )

        params = {"state": json.dumps({})}
        with MockRequest(self.env):
            db, login, token = self.env["res.users"].auth_oauth(
                self.provider_rec.id,
                params,
            )
        self._assert_token_kept_out(user, token, "1764")
        self.assertEqual(login, user.login)

    @responses.activate
    def test_login_without_kid_multiple_keys_in_jwks(self):
        """
        Test that login fails if no kid is provided in ID Token and JWKS has multiple
        keys
        """
        user = self._prepare_login_test_user()
        self._prepare_login_test_responses(
            id_token_body={"user_id": user.login},
            id_token_headers={},
            access_token="6*7",
            keys=[
                {"kid": "other_key_id", "keys": [self.second_key_public_pem]},
                {"kid": "the_key_id", "keys": [self.rsa_key_public_pem]},
            ],
        )

        with self.assertRaises(
            JWTError,
            msg="OpenID Connect requires kid to be set if there is"
            " more than one key in the JWKS",
        ):
            with MockRequest(self.env):
                self.env["res.users"].auth_oauth(
                    self.provider_rec.id,
                    {"state": json.dumps({})},
                )

    @responses.activate
    def test_login_without_matching_key(self):
        """Test that login fails if no matching key can be found"""
        user = self._prepare_login_test_user()
        self._prepare_login_test_responses(
            id_token_body={"user_id": user.login},
            id_token_headers={},
            access_token="168/4",
            keys=[{"kid": "other_key_id", "keys": [self.second_key_public_pem]}],
        )

        with self.assertRaises(JWTError):
            with MockRequest(self.env):
                self.env["res.users"].auth_oauth(
                    self.provider_rec.id,
                    {"state": json.dumps({})},
                )

    @responses.activate
    def test_login_without_any_key(self):
        """Test that login fails if no key is provided by JWKS"""
        user = self._prepare_login_test_user()
        self._prepare_login_test_responses(
            id_token_body={"user_id": user.login},
            id_token_headers={},
            access_token="168/4",
            keys=[],
        )

        with self.assertRaises(AccessDenied):
            with MockRequest(self.env):
                with self.assertLogs(level=logging.ERROR) as logs:
                    self.env["res.users"].auth_oauth(
                        self.provider_rec.id,
                        {"state": json.dumps({})},
                    )
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelno, logging.ERROR)
        self.assertEqual(
            "ERROR:odoo.addons.auth_oidc.models.res_users:user_id claim not found in"
            " id_token (after mapping).",
            logs.output[0],
        )

    @responses.activate
    def test_login_with_multiple_keys_in_jwks(self):
        """Test that login works with multiple keys present in jwks"""
        user = self._prepare_login_test_user()
        self._prepare_login_test_responses(
            id_token_body={"user_id": user.login},
            access_token="2*3*7",
            keys=[
                {"kid": "other_key_id", "keys": [self.second_key_public_pem]},
                {"kid": "the_key_id", "keys": [self.rsa_key_public_pem]},
            ],
        )

        with MockRequest(self.env):
            db, login, token = self.env["res.users"].auth_oauth(
                self.provider_rec.id,
                {"state": json.dumps({})},
            )
        self._assert_token_kept_out(user, token, "2*3*7")
        self.assertEqual(login, user.login)

    @responses.activate
    def test_login_with_multiple_keys_in_jwks_same_kid(self):
        """Test that login works with multiple keys with the same kid present in jwks"""
        user = self._prepare_login_test_user()
        self._prepare_login_test_responses(
            id_token_body={"user_id": user.login},
            access_token="84/2",
            keys=[
                {"kid": "the_key_id", "keys": [self.second_key_public_pem]},
                {"kid": "the_key_id", "keys": [self.rsa_key_public_pem]},
            ],
        )

        with MockRequest(self.env):
            db, login, token = self.env["res.users"].auth_oauth(
                self.provider_rec.id,
                {"state": json.dumps({})},
            )
        self._assert_token_kept_out(user, token, "84/2")
        self.assertEqual(login, user.login)

    @responses.activate
    def test_login_with_jwk_format(self):
        """Test that login works with proper jwks format"""
        user = self._prepare_login_test_user()
        self.rsa_key_public_jwk["kid"] = "the_key_id"
        self._prepare_login_test_responses(
            id_token_body={"user_id": user.login},
            keys=[self.rsa_key_public_jwk],
            access_token="122/3",
        )

        with MockRequest(self.env):
            db, login, token = self.env["res.users"].auth_oauth(
                self.provider_rec.id,
                {"state": json.dumps({})},
            )
        self._assert_token_kept_out(user, token, "122/3")
        self.assertEqual(login, user.login)

    # ------------------------------------------------------------------
    # Dibon port to 20.0: tokens in the session only, nonce and PKCE per sign-in
    # ------------------------------------------------------------------

    def _pending_in(self, request):
        self.env["auth.oauth.provider"].search(
            [("client_id", "!=", "auth_oidc-test")]
        ).write(dict(enabled=False))
        providers = OpenIDLogin().list_providers()
        self.assertNotIn("client_secret", providers[0])
        pending = request.session[keys.PKCE][str(self.provider_rec.id)]
        params = parse_qs(urlparse(providers[0]["auth_link"]).query)
        return pending, params

    def test_pkce_and_nonce_per_sign_in(self):
        with MockRequest(self.env) as request:
            first, params = self._pending_in(request)
            self.assertEqual(params["nonce"], [first["nonce"]])
            second, _params = self._pending_in(request)
        self.assertNotEqual(first["verifier"], second["verifier"])
        self.assertNotEqual(first["nonce"], second["nonce"])

    @responses.activate
    def test_tokens_kept_for_the_session(self):
        user = self._prepare_login_test_user()
        with MockRequest(self.env) as request:
            pending, _params = self._pending_in(request)
            self._prepare_login_test_responses(
                id_token_body={"sub": user.login, "nonce": pending["nonce"]}, access_token="the-access-token")
            responses.replace(
                responses.POST,
                "http://localhost:8080/auth/realms/master/protocol/openid-connect/token",
                json={
                    "access_token": "the-access-token", "refresh_token": "the-refresh-token", "expires_in": 300,
                    "id_token": jwt.encode({"sub": user.login, "nonce": pending["nonce"]}, self.rsa_key_pem,
                                           algorithm="RS256", headers={"kid": "the_key_id"}),
                },
            )
            _db, login, secret = self.env["res.users"].auth_oauth(self.provider_rec.id, {"state": json.dumps({})})
            tokens = request._auth_oidc_tokens
        self.assertEqual(login, user.login)
        self.assertEqual(tokens[keys.ACCESS_TOKEN], "the-access-token")
        self.assertEqual(tokens[keys.REFRESH_TOKEN], "the-refresh-token")
        self.assertGreater(tokens[keys.EXPIRES_AT], 0)
        self.assertNotIn("the-access-token", (user.sudo().oauth_access_token or ""))
        # the code verifier sent is this sign-in's, not a fixed one
        sent = parse_qs(responses.calls[0].request.body)
        self.assertEqual(sent["code_verifier"], [pending["verifier"]])

    @responses.activate
    def test_wrong_nonce_is_refused(self):
        user = self._prepare_login_test_user()
        with MockRequest(self.env) as request:
            self._pending_in(request)
            self._prepare_login_test_responses(id_token_body={"sub": user.login, "nonce": "replayed"})
            with self.assertRaises(AccessDenied), self.assertLogs(level=logging.ERROR):
                self.env["res.users"].auth_oauth(self.provider_rec.id, {"state": json.dumps({})})

    @responses.activate
    def test_sign_in_over_http_keeps_tokens_in_the_session(self):
        """The whole round trip: login page, Keycloak's callback, a signed-in session
        holding the tokens, and nothing of the provider's on the user record."""
        responses.add_passthru("http://127.0.0.1")
        responses.add_passthru("http://localhost:%s" % odoo.tools.config["http_port"])
        user = self._prepare_login_test_user()
        self.env["auth.oauth.provider"].search([("id", "!=", self.provider_rec.id)]).write({"enabled": False})
        self.url_open("/web/login")  # renders the providers: makes this session's verifier and nonce
        pending = self._session()[keys.PKCE][str(self.provider_rec.id)]
        responses.add(
            responses.POST,
            "http://localhost:8080/auth/realms/master/protocol/openid-connect/token",
            json={"access_token": "kc-access", "refresh_token": "kc-refresh", "expires_in": 300,
                  "id_token": jwt.encode({"sub": user.login, "aud": "auth_oidc-test", "nonce": pending["nonce"]},
                                         self.rsa_key_pem, algorithm="RS256", headers={"kid": "the_key_id"})},
        )
        responses.add(
            responses.GET,
            "http://localhost:8080/auth/realms/master/protocol/openid-connect/certs",
            json={"keys": [{"kid": "the_key_id", "keys": [self.rsa_key_public_pem]}]},
        )
        state = json.dumps({"d": self.env.cr.dbname, "p": self.provider_rec.id})
        self.url_open(f"/auth_oauth/signin?state={state}&code=the-code", allow_redirects=False)
        session = self._session()
        self.assertEqual(session.uid, user.id)
        self.assertEqual(session[keys.ACCESS_TOKEN], "kc-access")
        self.assertEqual(session[keys.REFRESH_TOKEN], "kc-refresh")
        self.assertNotIn(keys.PKCE, session)
        self.assertNotEqual(user.sudo().oauth_access_token, "kc-access")

    def _session(self):
        from odoo.http.session import session_store  # noqa: PLC0415

        return session_store().get(self.opener.cookies["session_id"], keep_sid=True)
