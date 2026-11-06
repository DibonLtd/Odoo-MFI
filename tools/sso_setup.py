#!/usr/bin/env python3
"""Set up Dibon SSO (Keycloak, through OCA auth_oidc) in an Odoo 19 database.

The provider and the user links are data in the database, not code, so run
this once per database: staging first, then production.

    python tools/sso_setup.py provider
        Create or update the "Dibon SSO" provider (authorization code flow,
        client secret, users linked by Keycloak's sub) and set sign-up to
        "on invitation", so a Keycloak account alone never creates a user.

    python tools/sso_setup.py users tools/users.csv [--apply]
        Link each user in the CSV to Keycloak by sub. A user already linked
        by that sub is updated; otherwise a user with the same login or email
        is linked; otherwise a new user is created with no password. Dry run
        unless --apply is given.

CSV columns: sub, email, name, groups (XML ids separated by spaces, e.g.
"base.group_user"). Groups listed are added; existing groups are kept.

Environment:
    ODOO_URL, ODOO_DB, ODOO_LOGIN, ODOO_API_KEY    an administrator's API key
    KEYCLOAK_ISSUER          e.g. https://sso.example.com/realms/dibon (provider)
    KEYCLOAK_CLIENT_SECRET   (provider)
    KEYCLOAK_CLIENT_ID       optional, default "odoo"

Uses only the standard library. Odoo 19 deprecates XML-RPC in favour of its
JSON-2 API, but XML-RPC still works in 19.
"""

import argparse
import csv
import os
import sys
import xmlrpc.client

PROVIDER_NAME = "Dibon SSO"


def env(name, default=None):
    value = os.environ.get(name, default)
    if not value:
        sys.exit(f"Set the environment variable {name}")
    return value


class Odoo:
    def __init__(self):
        self.url = env("ODOO_URL").rstrip("/")
        self.db = env("ODOO_DB")
        self.key = env("ODOO_API_KEY")
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.uid = common.authenticate(self.db, env("ODOO_LOGIN"), self.key, {})
        if not self.uid:
            sys.exit("Odoo refused the login and API key")
        self.rpc = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object", allow_none=True
        )

    def call(self, model, method, *args, **kwargs):
        return self.rpc.execute_kw(
            self.db, self.uid, self.key, model, method, list(args), kwargs
        )

    def group_id(self, xmlid):
        module, _, name = xmlid.partition(".")
        found = self.call(
            "ir.model.data", "search_read",
            [("module", "=", module), ("name", "=", name), ("model", "=", "res.groups")],
            fields=["res_id"], limit=1,
        )
        if not found:
            sys.exit(f"No group with XML id {xmlid}")
        return found[0]["res_id"]

    def provider_id(self):
        found = self.call(
            "auth.oauth.provider", "search", [("name", "=", PROVIDER_NAME)], limit=1
        )
        return found[0] if found else None


def setup_provider(odoo):
    oidc = env("KEYCLOAK_ISSUER").rstrip("/") + "/protocol/openid-connect"
    values = {
        "name": PROVIDER_NAME,
        "flow": "id_token_code",
        "client_id": env("KEYCLOAK_CLIENT_ID", "odoo"),
        "client_secret": env("KEYCLOAK_CLIENT_SECRET"),
        "token_map": "sub:user_id",
        "scope": "openid profile email",
        "auth_endpoint": f"{oidc}/auth",
        "token_endpoint": f"{oidc}/token",
        "jwks_uri": f"{oidc}/certs",
        "body": "Log in with Dibon SSO",
        "enabled": True,
    }
    existing = odoo.provider_id()
    if existing:
        odoo.call("auth.oauth.provider", "write", [existing], values)
        print(f"Updated provider {PROVIDER_NAME} (id {existing})")
    else:
        new_id = odoo.call("auth.oauth.provider", "create", values)
        print(f"Created provider {PROVIDER_NAME} (id {new_id})")
    # "On invitation": no free sign-up, so an unlinked Keycloak user is refused.
    odoo.call("ir.config_parameter", "set_param", "auth_signup.invitation_scope", "b2b")
    print("Sign-up set to on invitation")
    print(f"Redirect URI for Keycloak: {odoo.url}/auth_oauth/signin")


def link_users(odoo, path, apply):
    provider = odoo.provider_id()
    if not provider:
        sys.exit(f"Run 'provider' first: no provider named {PROVIDER_NAME}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    missing = {"sub", "email", "name"} - set(rows[0] if rows else [])
    if missing:
        sys.exit(f"CSV is missing columns: {', '.join(sorted(missing))}")

    group_cache = {}
    for row in rows:
        sub, email, name = row["sub"].strip(), row["email"].strip().lower(), row["name"].strip()
        if not (sub and email and name):
            print(f"SKIP  incomplete row: {row}")
            continue
        groups = []
        for xmlid in (row.get("groups") or "").split():
            if xmlid not in group_cache:
                group_cache[xmlid] = odoo.group_id(xmlid)
            groups.append(group_cache[xmlid])

        by_sub = odoo.call(
            "res.users", "search",
            [("oauth_uid", "=", sub), ("oauth_provider_id", "=", provider)],
            context={"active_test": False},
        )
        by_login = odoo.call(
            "res.users", "search",
            ["|", ("login", "=ilike", email), ("email", "=ilike", email)],
            context={"active_test": False},
        )
        link = {"oauth_provider_id": provider, "oauth_uid": sub}
        if groups:
            link["group_ids"] = [(4, g) for g in groups]

        if by_sub:
            action, ids = "UPDATE", by_sub
        elif len(by_login) == 1:
            action, ids = "LINK", by_login
        elif len(by_login) > 1:
            print(f"SKIP  {email}: {len(by_login)} users match this email; link by hand")
            continue
        else:
            action, ids = "CREATE", None

        print(f"{action:6} {email} -> sub {sub}")
        if not apply:
            continue
        if ids:
            odoo.call("res.users", "write", ids, link)
        else:
            odoo.call(
                "res.users", "create",
                {"name": name, "login": email, "email": email, **link},
                context={"no_reset_password": True},
            )
    if not apply:
        print("Dry run: nothing changed. Add --apply to write.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("provider")
    users = sub.add_parser("users")
    users.add_argument("csv")
    users.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    odoo = Odoo()
    if args.command == "provider":
        setup_provider(odoo)
    else:
        link_users(odoo, args.csv, args.apply)


if __name__ == "__main__":
    main()
