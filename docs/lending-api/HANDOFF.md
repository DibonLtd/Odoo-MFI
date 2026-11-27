# Handoff: Microfinance in Odoo over the Kapu lending API

For whoever picks this up next, and for the backend team providing the API.
- Why things are as they are: [DECISIONS.md](DECISIONS.md).
- What is done and what is next: [TASKLIST.md](TASKLIST.md).

Last updated 2026-11-25.

## 1 · State now

| Area | State |
|---|---|
| Odoo | 20.0 Enterprise (`20.0+e.20261116`) |
| API contract | `Requirements/kapu-lending.v1.yaml`, 1.0.0-draft.1: slice 1, individual onboarding |
| Onboarding through the API | **Built and tested against the stub's answers**; not yet run against the real lending service |
| Loans, approvals, payouts, repayments, collections, products | Local Odoo records, unchanged (D-001); each moves when its slice ships (TASKLIST phase 6) |
| Sign-in | Odoo's own login. The connection runs in `static` or `service_account` mode. `token_exchange` is built but waits for Keycloak sign-in (LA-40, LA-41) |
| Tests | 122 on a fresh database, all passing: 67 earlier, 28 connector, 24 onboarding, 3 in the browser. Two of the connector's 28 are live-stub tests, skipped until a stub runs (LA-17) |

## 2 · What was built

### `mfi_lending_api`: the connector (new addon; depends on `base`, `web`, `base_setup`)

| File | What |
|---|---|
| `services/client.py` | `LendingClient`: one method per operation, headers, timeouts, logging without personal data. The PUT to the upload address goes only to allowed hosts, with no token |
| `services/auth.py` | Token providers: `static`, `service_account` (cached in memory), `token_exchange` (RFC 8693, held in the HTTP session) |
| `services/config.py` | Settings from system parameters. Secrets only from `odoo.conf` or the environment |
| `services/errors.py` | `LendingRefusal`, `LendingUnavailable`, `LendingNotConfigured`; text for all 21 refusal codes |
| `models/lending_command.py` | `mfi.lending.command`: the idempotency store and the log of writes, on a cursor of its own; a daily clean-up after 13 months |
| `models/res_config_settings.py`, `views/` | Settings → Kapu lending; Test connection; the command log |
| `i18n/sw.po` | Swahili refusal texts, **to be reviewed by Roan Capital** |
| `tests/` | `common.py`: `StubTransport`, which replays `fixtures/lending.json` (a copy of `Requirements/lending.json`) like WireMock, with priorities, header-absent rules and `X-Stub-Example`. `test_stub_live.py`: against a real stub |

### `mfi_loan`: onboarding

| File | What |
|---|---|
| `models/res_partner.py` | **New fields:** first, middle and last name (the name is composed from them); ID type; date of birth; consent to checks, with when and by whom; county, town, street, landmark; primary next of kin. **Sync fields:** lending id (unique), sync state, sent at and by. **Rules:** details locked after a push (D-004); a document's file may be gone once the service stores it |
| `models/res_partner_lending.py` | **Actions:** the form button and the list action (bulk). **RPCs for the screens:** `mfi_lending_push`, `mfi_lending_read`, `mfi_lending_command`, `mfi_lending_list` |
| `services/lending.py` | **Mapping:** `create_body`, `contact_patch`, `DOCUMENT_TYPES`. **Local checks:** `local_problems`. **`Onboarding`:** the push, the live reads, the screen's commands, and the purge of stored files |
| `static/src/lending/` | **OWL client actions:** `mfi_loan.lending_onboarding` (one client), `mfi_loan.lending_push` (the bulk dialog), `mfi_loan.lending_clients` (the live list) |
| `views/` | **Client form:** *Create in lending service* and *Onboarding* buttons, new fields, a *Lending service* tab, notices. **Client list:** a filter and badge. **Menus:** *Create in lending service* in the Action menu; Clients → *Lending service clients* |
| `models/rules.py` | New permission `lending.push`: Super Admin, Head Office, Credit Manager, Loan Officer |

### The flow, as staff see it

1. **Capture the client in Odoo.**
   - Fill in first and last name, ID type and number, date of birth, phone, email, and the address.
   - Mark one next of kin as primary.
   - Attach the ID and photo.
   - **Tick consent to checks only when the client has given it.**
2. **Create in lending service** (on the form), or select several clients → Action → *Create in lending service*.
   - The client is created, the contact details sent, and the ID and photo uploaded. The client is then `DRAFT` in the service.
   - Refusals are explained per client.
   - Running it again continues: nothing is done twice.
3. **Onboarding** (form button), with the client present:
   1. Send the code, and confirm the 6 digits the client reads out.
   2. Upload any missing document, or send the client an upload link.
   3. Submit. The checks then run and the screen follows them.
   4. *Correction needed* names the field. *Under review* shows nothing more (no tipping off).
4. **After the push,** the onboarding details are read-only in Odoo. Contact changes go through the onboarding screen and update the local copy (D-004).
   - The local ID and photo files are deleted once the service reports them `STORED`.
   - Loans keep working locally (D-013).

## 3 · Running it

### Against the WireMock stub (local)

```bash
docker run --rm -p 8094:8080 \
  -v "$PWD/Requirements:/home/wiremock/mappings" wiremock/wiremock:3.13.1
```

**Settings → Kapu lending:**
- Connect: on.
- Address: `http://localhost:8094`.
- Sign-in: *Static token*.
- Document upload hosts: `vault.example.invalid`.
- Tick *Skip the file transfer (stub only)*: the stub's upload addresses point nowhere.
- *Stub example* picks a named answer for every call, e.g. `phone_not_confirmed`, `documents_missing`, `held`, `too_many_requests`. Leave it empty for the defaults.

Then press **Test connection**. The stub keeps no state: a client you create does not appear in a later read.

### Against the lending service

**Settings:**
- Address: `https://…` (plain http is refused outside the stub).
- Sign-in: *Service account* now; *Token exchange* once LA-41 is done.
- Keycloak token address: `…/realms/staff/protocol/openid-connect/token`.
- Client: `odoo`. Audience: `lending-service`.
- Document upload hosts: the vault's host.

**Secrets, in `odoo.conf`** (or the environment, upper-case), **never in Settings:**

```ini
kapu_lending_client_secret = …   ; service_account and token_exchange
kapu_lending_static_token = …    ; static mode against a real service only
```

### Tests

```bash
O=/path/to/odoo-20; PYTHONPATH=$O python $O/setup/odoo -c odoo.conf \
  --addons-path=$O/odoo/addons,$PWD -d test_db -i mfi_loan,mfi_loan_demo \
  --test-enable --test-tags /mfi_loan,/mfi_loan_demo,/mfi_lending_api --stop-after-init
# against a running stub as well:
KAPU_LENDING_STUB_URL=http://localhost:8094 … --test-tags /mfi_lending_api:TestStubLive
```

**Two traps** for anyone writing tests here:

1. **The command log writes on its own cursor.** A test class must be in registry test mode (`cls.enterClassContext(cls.registry_test_mode())`; HttpCase already is), or the rows are committed to the real database.
2. **Odoo's `assertRaises` rolls back a savepoint,** which in tests also erases those rows. Use `unittest.TestCase.assertRaises(self, …)` when asserting on the log after a refusal.

## 4 · Operating it

- **Command log:** Settings → Kapu lending → *Command log*.
  - One row per write: operation, outcome, HTTP status, refusal code, and the `traceId` to quote to the backend team.
  - No personal data.
  - Rows older than 13 months are removed daily.
- **Python logs:** each call is logged as `lending METHOD /path/template -> status in Nms trace=…`.
- **A push that failed:** the client shows *Not sent*; the reason is in the notification and the command log. Correct it and press the button again.
- **The service is down:** nothing is lost. The push and commands say so, and pressing again reuses the same key (D-006).

## 5 · Where the code deviates from the target design

| Deviation | Why | Closed by |
|---|---|---|
| A local copy of the client's personal data stays after the push (D-004) | Reads are masked and reveal is 501; local loans, SMS and M-Pesa matching need the phone | LA-80 |
| `service_account` mode makes the service, not the person, the actor in the lending service (D-005) | Keycloak sign-in to Odoo is not live | LA-40, LA-41 |
| A client secret instead of a signed client assertion (D-016) | No OpenBao in the instance yet | LA-44 |
| Local loans for clients not yet `ACTIVE` (D-013) | Loans are local until their slice | LA-60 |

## 6 · Questions for the backend team

| # | Question | Why it matters to Odoo |
|---|---|---|
| Q-01 | The document-type catalogue: the full list of `documentType` values and which are required when | Odoo maps three of its kinds (`DOCUMENT_TYPES`); other types are uploaded by name |
| Q-02 | Proposal A1: may name, ID number and date of birth be changed by PATCH? | A correction (`CORRECT_FIELD`) on `dateOfBirth` has no path today. The screen asks staff to check it with the client |
| Q-03 | Plan question 3: the step-up contract for `/reveal` | Needed before Odoo can drop its local copy of personal data (LA-68, LA-80) |
| Q-04 | Plan question 2: the upload flow. Will the upload address be HTTPS on a fixed vault host? Size limit? | Odoo sends only to listed hosts (D-015) and refuses files over 10 MB (proposed) |
| Q-05 | Plan question 6: what a failed check shows | The screen has no "failed" outcome; `HELD` shows nothing |
| Q-06 | Plan question 18: when the KRA PIN is checked, and is the certificate always required with a PIN? | The checklist decides; Odoo follows it |
| Q-07 | `confirm_phone` appears in no example's `actions`. When is it listed? | The screen shows the confirm box whenever the phone is unconfirmed and a code can be sent |
| Q-08 | Business clients: which slice? | They stay local until then (D-010) |
| Q-09 | A bulk or import path for existing clients, and the consent evidence it needs | Today each is pushed one call at a time (LA-81) |
| Q-10 | Is `Idempotency-Key` kept long enough for a retry the next day? | Odoo reuses a key for an unfinished action for up to 13 months |
| Q-11 | Token exchange (access K15): will `auth_oidc` on Odoo 20 exist, and how will the person's token reach the session without being stored on the user record? | LA-40, LA-41 |

## 7 · Next tasks

1. Run the live-stub test against WireMock (LA-17); then against the lending service in a test instance, with a service account.
2. Guides for the new screens (LA-37), and Swahili for the screens (LA-52); Roan Capital to review the Swahili.
3. Keycloak sign-in and token exchange (LA-40 to LA-42), when OCA `server-auth` supports Odoo 20.
4. Sample data: give `mfi_loan_demo`'s clients first and last names, a date of birth and consent, so the push can be shown against the stub.
5. When the next API slice arrives: add its operations to `LendingClient` with tests from its stub, then follow TASKLIST phase 6.

## 8 · Change log

| Date | Change |
|---|---|
| 2026-11-25 | Planning documents. `mfi_lending_api` connector. Onboarding in `mfi_loan`: fields, push (one and bulk), onboarding screen, live list. 55 new tests (28 connector, 24 onboarding, 3 browser); 122 in all |
| 2026-11-25 | Reuse Odoo, first part (D-017 to D-020; TASKLIST LR-01 to LR-09): local loans booked in Accounting (loan invoice with a daily payment term, payouts, fees, default interest, settlement and write-off credit notes); repayments are standard payments applied oldest first; collections are activities; reminders are Accounting's follow-up; dashboard figures from the ledger. Deleted: instalment, payment and collection-note models, the allocation engine, the reminder cron, the report wizard. Fresh database: 119 tests pass |
| 2026-11-27 | Keycloak: `auth_oidc` ported from OCA 19.0 to Odoo 20 (tokens in the session only, PKCE and nonce per sign-in); the connector renews and exchanges the session token; [KEYCLOAK.md](KEYCLOAK.md) lists what the Keycloak administrator and the MFI team must provide |
