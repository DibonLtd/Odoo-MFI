# Copyright 2026 Dibon
# License: AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""What sign-in keeps in the person's HTTP session, never in the database
(access-keycloak §7, check K15). Other modules read these keys, so they are a
contract: mfi_lending_api exchanges ACCESS_TOKEN for its own audience and
renews it with REFRESH_TOKEN."""

PKCE = "auth_oidc.pkce"  # {provider id: {"verifier": ..., "nonce": ...}} until sign-in completes
ACCESS_TOKEN = "auth_oidc.access_token"
REFRESH_TOKEN = "auth_oidc.refresh_token"
EXPIRES_AT = "auth_oidc.expires_at"  # epoch seconds
PROVIDER = "auth_oidc.provider_id"
