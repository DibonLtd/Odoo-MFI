# Connecting Odoo, Keycloak and the MFI backend

Keycloak runs on DigitalOcean, and the MFI backend (the Kapu lending service)
already uses it. Odoo uses it in two ways:

1. **Staff sign in to Odoo through Keycloak.** Code flow with PKCE, through the `odoo` client (`auth_oidc`, in this repository).
2. **Odoo calls the MFI API as the signed-in person.** For each call, Odoo exchanges the person's Keycloak token for one addressed to the lending service, still naming the person (standard token exchange; access-keycloak §7). No token is ever stored in Odoo's database: tokens live in the person's session only.

```
 staff browser ──sign in (code + PKCE)──▶ KEYCLOAK (DigitalOcean)
      │                                     ▲   │ access + refresh token
      ▼                                     │   ▼
    ODOO ──token exchange: audience lending-service──┘
      │
      └──API call, Bearer <exchanged token>──▶ MFI BACKEND (validates: realm, audience, roles)
```

Sections A and B are written to be sent as they are. Secrets (client secrets) go
through a password manager or another secure channel, never by email or chat.

---

## A · From the Keycloak administrator (DigitalOcean)

1. **The realm.** Its name and its issuer URL, `https://<keycloak-host>/realms/<realm>`.
2. **The Keycloak version.** Standard token exchange needs **26.2 or later**.
3. **A client `odoo`:**
   - Client authentication **on** (confidential). Standard flow **on**. Implicit flow and direct access grants **off**.
   - PKCE method **S256** (Advanced → "Proof Key for Code Exchange Code Challenge Method").
   - **Standard Token Exchange: on** (Capability config).
   - Valid redirect URIs: `https://roan-odoo.dibon.co.ke/auth_oauth/signin`, and the staging host's equivalent.
   - Web origins: the same hosts. Valid post-logout redirect URIs: `https://roan-odoo.dibon.co.ke/*`.
   - Send the **client secret** through a secure channel.
4. **Odoo may ask for the lending service's audience.** The tokens `odoo` exchanges must be allowed to carry audience `lending-service`, the MFI backend's client. For example: a client scope with an *Audience* mapper for `lending-service`, assigned to the `odoo` client. Confirm the exact client id the MFI backend validates.
5. **Token lifetimes.** Access tokens of 5 minutes (access-keycloak S22). Also send the SSO session idle and maximum times, so Odoo's own session limits can match them.
6. **Staff.**
   - Every staff member has an account in this realm, with two-factor authentication.
   - Groups or roles for Roan Capital's eight positions (Super Admin, CEO, Head Office, Credit Manager, Loan Officer, Finance, Collections, Auditor), with their exact names.
   - An export of each staff member's `sub` (user id), email and name. Odoo links users by `sub`, never by email.
7. **Network.**
   - Keycloak is reachable from the Odoo server over HTTPS (443), with a valid certificate.
   - The issuer host is the same name from the browser and from the server.
   - The DigitalOcean firewall allows the Odoo server's outbound traffic to it.
8. **Interim only (optional).** A service-account client for Odoo (client credentials, audience `lending-service`). This is used only if the MFI team accepts service tokens until sign-in through Keycloak is live. Every act is then recorded against the service, not the person.

## B · From the MFI (lending service) team

1. **API addresses** for staging and production (HTTPS).
2. **Contract.** Is the deployed API `kapu-lending.v1.yaml` 1.0.0-draft.1 (in `Requirements/`), or a newer one? Send the newer contract and its WireMock stub if so.
3. **How the API checks Odoo's tokens:**
   - The client id / audience it validates (expected `lending-service`).
   - Confirmation that it accepts **exchanged** tokens whose `azp` is `odoo`, from the staff realm.
   - Which claim carries the roles: `realm_access.roles` or `resource_access.<client>.roles`.
4. **Roles.** The role names the API checks for each operation (for example `client.create`), and which staff positions hold them.
5. **Interim.** Whether the API accepts a service-account token until token exchange is live, and from which client.
6. **Document uploads.** The host or hosts in the upload addresses the API returns. Odoo sends files only to listed hosts.
7. **Network.** Whether the API is IP-allowlisted. If so, Odoo's outbound IP must be added.
8. **Staging.** A staging environment with one test user per role.
9. **Open questions:** answers to [HANDOFF.md](HANDOFF.md) §6, Q-01 to Q-11 (document types, corrections, step-up for reveal, and others).

---

## C · Odoo side

### Before anything else

The production server's Odoo Community and Enterprise must come from the same
build: the `account_reports` upgrade error, and the missing `mfi_loan.dashboard`
action, both point to a mismatch. Then update `base`, then `mfi_loan`.

### Sign-in (`auth_oidc`)

1. Deploy this repository. It includes `auth_oidc`, ported to Odoo 20 (DECISIONS D-021). `python-jose` is in `requirements.txt`.
2. Apps → install **Authentication OpenID Connect** (`auth_oidc`).
3. Set the provider and link the users (`tools/sso_setup.py`; README, "Single sign-on with Keycloak"):

   ```bash
   export ODOO_URL=https://roan-odoo.dibon.co.ke ODOO_DB=<db> ODOO_LOGIN=<admin> ODOO_API_KEY=<key>
   export KEYCLOAK_ISSUER=https://<keycloak-host>/realms/<realm> KEYCLOAK_CLIENT_SECRET=<odoo client secret>
   python tools/sso_setup.py provider
   python tools/sso_setup.py users tools/users.csv          # dry run: what would change
   python tools/sso_setup.py users tools/users.csv --apply
   ```

4. Keep one administrator with a password until everyone signs in through Keycloak.

### The MFI API connection (`mfi_lending_api`)

Settings → Kapu lending:

| Setting | Value |
|---|---|
| Service address | the MFI API's HTTPS address (B1) |
| Sign-in | *Token exchange as the signed-in person*. Use *Service account* only in the interim (A8, B5) |
| Keycloak token address | `https://<keycloak-host>/realms/<realm>/protocol/openid-connect/token` |
| Keycloak client | `odoo` |
| Audience | `lending-service`, or the id from B3 |
| Document upload hosts | from B6 |

In `odoo.conf` (never in Settings):

```ini
kapu_lending_client_secret = <the odoo client's secret>
```

Then, signed in through Keycloak, press **Test connection**.

### Order of rollout

1. Fix the build mismatch (above).
2. Collect A and B.
3. Staging: sign-in, then *Service account* mode and Test connection, then *Token exchange* and Test connection, then onboard one test client end to end.
4. Production: the same.
5. Once stable, staff stop using Odoo passwords (TASKLIST LA-43).

### What happens behind the screens

- **At sign-in.** Keycloak returns an access token and a refresh token. They stay in the person's Odoo session (server side), never on the user record. Odoo's own sign-in check uses a random one-time secret instead (D-021).
- **For each MFI call.** Odoo renews the person's access token with the refresh token when it is about to expire, then exchanges it for a token addressed to the lending service. That token is kept in the session until it expires.
- **When the Keycloak session ends** (idle or signed out), the next MFI call asks the person to sign in again. Odoo pages keep working until Odoo's own session ends.
