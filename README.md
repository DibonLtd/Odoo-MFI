# Odoo-MFI

Dibon's Odoo 19 Enterprise add-ons for microfinance, deployed on Odoo.sh.

## Layout

| Path | What |
|---|---|
| `server-auth/` | OCA server-auth, branch 19.0, as a git submodule. Provides `auth_oidc` (Keycloak sign-in) |
| `requirements.txt` | Python packages Odoo.sh installs on build (`python-jose` for `auth_oidc`) |
| `tools/sso_setup.py` | Sets up the Keycloak provider and links users, per database |

Custom modules go at the repository root, beside `server-auth/`.

## Single sign-on with Keycloak (phase 1: login only)

Keycloak says who the user is; Odoo keeps its own groups and access rights.
Users are linked by Keycloak's `sub`, never by email, and are created in
advance: free sign-up stays off, so a Keycloak account alone never creates
an Odoo user.

1. Push; wait for a green build on the staging branch.
2. Apps → Update Apps List → install **Authentication OpenID Connect**
   (`auth_oidc`). Install without demo data: its demo provider links users
   by username, not `sub`.
3. Create an administrator API key (Preferences → Account Security), then:

   ```bash
   export ODOO_URL=https://<staging-host> ODOO_DB=<db> ODOO_LOGIN=<admin> ODOO_API_KEY=<key>
   export KEYCLOAK_ISSUER=https://<keycloak-host>/realms/<realm> KEYCLOAK_CLIENT_SECRET=<secret>
   python tools/sso_setup.py provider
   python tools/sso_setup.py users tools/users.csv          # dry run
   python tools/sso_setup.py users tools/users.csv --apply
   ```

   `tools/users.csv` follows `tools/sso_users.example.csv` and is ignored by
   git: it holds Keycloak ids and emails.
4. Keep at least one administrator with a password: the standard login form
   is the fallback during rollout.
5. Run the acceptance tests in the integration brief, then repeat steps 2
   and 3 in production. Staging and production each need their redirect URI,
   `https://<host>/auth_oauth/signin`, registered in Keycloak.

### Known behaviour

- `auth_oidc` has no discovery URL support; `sso_setup.py` sets the
  endpoints from the issuer.
- With the code flow, identity comes from the ID token; the UserInfo
  endpoint is not called.
- An unlinked Keycloak user is refused with Odoo's standard "You do not have
  access to this database" message, and no user is created.
- Logging out of Odoo does not end the Keycloak session.
- A user disabled in Keycloak cannot start a new session; an Odoo session
  already open lasts until it expires.

### Integration users

Services that call Odoo's API use an Odoo user per service, with only the
groups it needs and its own API key; they have no Keycloak link. Odoo 19
deprecates `/xmlrpc` and `/jsonrpc` in favour of the JSON-2 API (`/json/2`).
