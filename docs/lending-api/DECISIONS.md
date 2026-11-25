# Decisions: Microfinance in Odoo over the Kapu lending API

How `mfi_loan` moves from keeping everything in Odoo to being the staff
interface over the Kapu lending service. Each decision gives what was decided,
why, its source, and what follows from it. A new decision gets the next number.
A decision is never edited in place: replace it with a new one, and mark the
old one *Superseded by D-xxx*.

**Sources** (in `finance-main/docs/`, unless marked):
- `specs/staff-workspace.md`: Odoo is the interface.
- `architecture/README.md` §2: three authorities, and "reference by id; never copy".
- `specs/back-office.md` rule 1: no business rule in the ERP.
- `modules/business-suite.md`: BS-23.
- `specs/access-keycloak.md` §5 and §7: sign-in and token exchange.
- `journeys/manual-identity-check.md` (JN-02).
- **In this repo:** `Requirements/kapu-lending.v1.yaml`, the API contract (slice 1, individual onboarding).
- **In this repo:** `Requirements/lending.json`, its WireMock stub.

| # | Decision | Status |
|---|---|---|
| D-001 | Odoo is the interface; each feature moves to the API when its slice ships | Accepted |
| D-002 | A separate connector addon, `mfi_lending_api` | Accepted |
| D-003 | Capture in Odoo first, then an explicit push to the lending service | Accepted |
| D-004 | Reference only, with a temporary local copy of personal data | Accepted, deviation |
| D-005 | Pluggable authentication; token exchange is the production target | Accepted |
| D-006 | Idempotency keys stored per action | Accepted |
| D-007 | Reads are live and never stored; the ETag is read fresh | Accepted |
| D-008 | Screens show only the actions the API returns | Accepted |
| D-009 | The push stops at a backend draft; phone and submit need the borrower present | Accepted |
| D-010 | Business clients stay local until the API supports them | Accepted |
| D-011 | Bulk push runs in the person's own requests, never in the background | Accepted |
| D-012 | The command log holds references only; refusals in English and Swahili | Accepted |
| D-013 | Local loans are not yet gated on the backend client state | Accepted, temporary |
| D-014 | Missing API planning documents are tracked as questions | Accepted |
| D-015 | Files pass through Odoo's own call, never a route of their own | Accepted |
| D-016 | Service account by client secret for now; signed client assertion is the target | Accepted, temporary |

---

## D-001 · Odoo is the interface; each feature moves to the API when its slice ships

**Decision.** `mfi_loan` becomes the staff workspace over the Kapu lending
service. Client onboarding uses the lending API now (slice 1). Loans,
approvals, disbursement, payments, collections, products and partners stay as
local Odoo records, working as they do today, until the API slice for each
exists. Each then moves to the API in a task of its own (TASKLIST phases 6
onwards).

**Why.**
- The target design: Odoo only shows and asks, the lending service lends, and Fineract records (staff-workspace §1, rules 1 to 3).
- The backend ships in slices, and Roan Capital needs the whole loan cycle working in the meantime.

**Consequences.**
- For a time, two kinds of data live side by side: references to the lending service (clients), and local records (everything else).
- Every screen states which kind it shows.
- Every feature's local model is temporary and is removed when its API arrives.

## D-002 · A separate connector addon, `mfi_lending_api`

**Decision.** All HTTP, authentication, error mapping and idempotency live in
a new addon, `mfi_lending_api`, which depends on `base` and `web` only and
holds no business rule. `mfi_loan` depends on it and holds the screens and the
mapping from Odoo fields to the API.

**Why.**
- The workspace must run on Odoo Community as well (staff-workspace rule 7; back-office rule 1).
- One connector, tested alone against the stub, serves every later slice.
- Keeping transport apart from screens keeps each small.

**Consequences.**
- New slices add operations to `LendingClient`, with tests.
- The connector never imports `mfi_loan`.

## D-003 · Capture in Odoo first, then an explicit push to the lending service

**Decision.**
- A client is captured in Odoo as today.
- A **Create in lending service** button pushes the client. A list action pushes several selected clients.
- Until pushed, a client is *local only*. Nothing is ever pushed automatically.

**Why.**
- The product owner's choice (2026-11-25): staff keep working when the service is unreachable, and existing local clients can be onboarded one by one or in bulk.
- Creating a client is an officer's command, never automatic (API `createClient`; business-suite BS-20).

**Consequences.**
- A client can be in Odoo and not yet in the lending service. The partner shows this (`mfi_lending_sync`: local, in lending service, push failed).
- Pushing checks locally first: consent recorded, an individual, date of birth, ID type. A refusal is explained and makes no call.

## D-004 · Reference only, with a temporary local copy of personal data

**Decision.**
- Once pushed, Odoo keeps the lending service's client id (`mfi_lending_client_id`) as the link.
- The local personal data (ID number, date of birth, KRA PIN, phone, addresses, next of kin) **stays, read-only, until loans move to the API**. Changes go through the API, and the local copy is updated with them.
- A local document file is deleted once the lending service reports that document `STORED`. A note records that it is stored there.

**Why.**
- The rule is "reference by id; never copy" (architecture §2), so this is a **deviation**.
- It is needed because the API returns personal data masked (last three characters), and reveal answers 501 in slice 1 (it needs step-up).
- The local loan features still need the real phone: matching M-Pesa payments, SMS and WhatsApp reminders.
- Documents are copied once only: the vault is their home (architecture §2, "Odoo never holds documents with personal data").
- The product owner chose this (2026-11-25).

**Consequences.**
- A task (LA-80) purges the local copy when loans, payments and collections run on the API, or when reveal with step-up exists. That task closes this deviation.
- Until then, the local copy is treated as Restricted: masked in lists, revealed with a password and logged, as today.

## D-005 · Pluggable authentication; token exchange is the production target

**Decision.** The connector gets its bearer token from one of three providers,
chosen in Settings:

| Mode | For | How |
|---|---|---|
| `static` | The WireMock stub, local development | A fixed token from configuration |
| `service_account` | The interim, before Keycloak sign-in to Odoo is live | Client credentials at Keycloak, audience `lending-service` |
| `token_exchange` | Production | The signed-in person's token, exchanged at Keycloak for one addressed to `lending-service` (access-keycloak §7) |

- Secrets (client secret, static token) come from `odoo.conf` or the environment, never from the database.
- An exchanged token lives in the person's HTTP session until it expires and is never written to the database.

**Why.**
- Every act must be recorded against the person (staff-workspace rule 4).
- Keycloak sign-in through OCA `auth_oidc` is not yet in this repository, and no OCA `server-auth` 20.0 branch is confirmed.
- The product owner chose both modes (2026-11-25).

**Consequences.**
- In `service_account` mode, the lending service records the service as the actor. Odoo's own audit log still names the person.
- Production must not go live on `service_account` for longer than agreed. The decision to do so is recorded on the deployment's page.
- K15 (access-keycloak §12): `auth_oidc` keeps the access token on the user record. Token exchange must read the person's token from the session instead (LA-41).

## D-006 · Idempotency keys stored per action

**Decision.**
- Every POST carries an `Idempotency-Key`.
- Odoo stores each command (`mfi.lending.command`): operation, client, key, a SHA-256 hash of the request body, outcome, HTTP status, refusal code, `traceId`, who and when.
- Retrying the same operation for the same client with the same body hash, after a pending or unavailable attempt, **reuses the key**. A changed body is a new action with a new key.

**Why.**
- The API returns the first answer for a repeated key and never acts twice. The same key with a different body is refused (`idempotency_key_reused`).
- Odoo may time out, or a person may click twice. Storing the key makes every retry safe, including bulk pushes that are run again.

**Consequences.**
- `request_in_progress` (409) is retried with the same key.
- The command log is the record of what Odoo asked for.

## D-007 · Reads are live and never stored; the ETag is read fresh

**Decision.**
- Client details, checklists, documents and verifications are fetched when a screen opens and shown with their `fetchedAt`. They are never written to Odoo's database.
- Before a PATCH or a submit, Odoo reads the client again for its `ETag`.
- A 412 `stale_version` re-reads and shows the person what changed.

**Why.** Reads are live, never stored (staff-workspace rule 1; API description).

**Consequences.**
- Lists of lending-service clients are paged live from the API (`listClients`).
- The partner list can filter on Odoo's own push outcome, but not on the backend state.

## D-008 · Screens show only the actions the API returns

**Decision.**
- The onboarding screen offers a command only when it is in the client's `actions`.
- Odoo never sets a backend state and never decides eligibility.
- Odoo's own groups decide which menus and buttons show; the API's `not_permitted` (403) is shown when the person's Keycloak roles refuse an act.

**Why.**
- "Odoo never sets a state" (API).
- Roles decide what shows (staff-workspace rule 6).
- No rule lives in the ERP (back-office rule 1).

## D-009 · The push stops at a backend draft; phone and submit need the borrower present

**Decision.**
- The push does these steps: create the client, update its contact details, upload the documents already held.
- Phone confirmation (one-time code) and submit happen in the onboarding screen, with the borrower present, one client at a time.

**Why.**
- The code goes to the borrower's phone, and submit is refused until the phone is confirmed (JN-01 §3 k).
- A bulk push therefore cannot finish onboarding.

## D-010 · Business clients stay local until the API supports them

**Decision.** Pushing a business client is refused locally with a reason.
Business clients keep working as local records.

**Why.** Slice 1 supports `type: INDIVIDUAL` only.

## D-011 · Bulk push runs in the person's own requests, never in the background

**Decision.** The bulk push is driven from the browser: one call per client,
in the person's session, with progress and a result for each. No scheduled
job pushes clients.

**Why.**
- A background job has no person's token, so it could not act as the person (D-005).
- It would also hide refusals the person must act on.

**Consequences.** Closing the browser stops a bulk push. Running it again
continues safely (D-006).

## D-012 · The command log holds references only; refusals in English and Swahili

**Decision.**
- The command log and Python logs hold references only: the operation, Odoo's record id, the lending-service id, the key, the status, the code and `traceId`. Never a request body, name, phone, ID number or file.
- The log is kept 13 months.
- Each of the API's 21 refusal codes has a message in English and Swahili. The field at fault is named, and `traceId` is shown for reporting.

**Why.**
- The call log keeps references only, for 13 months (staff-workspace §6, §7).
- Branch on `code`, never on `detail`; `detail` is for developers (API).
- Every message in English and Swahili (staff-workspace rule 10).

## D-013 · Local loans are not yet gated on the backend client state

**Decision.** A loan can still be captured locally for a client that is local
only, or not yet `ACTIVE` in the lending service.

**Why.**
- Loans are local until their slice ships (D-001).
- Gating them on a live read now would stop daily work whenever the service is unreachable.

**Consequences.** When loans move to the API, the lending service decides
(LA-60), and this decision is superseded.

## D-014 · Missing API planning documents are tracked as questions

**Decision.** The API description cites documents this repository does not
hold: `staff-api-plan.md` (plan questions 2, 3, 6 and 18, proposals A1 and A2)
and `docs/tasks/step-2-conventions.md`.

- Where they leave a behaviour open, Odoo follows the contract and its examples.
- The gap is listed in HANDOFF.md's questions for the backend team.

**Consequences.**
- The document-type catalogue is not fixed. Odoo's mapping of its document kinds to the API's types is configuration in one place (`DOCUMENT_TYPES`), so it can change without touching screens.

## D-015 · Files pass through Odoo's own call, never a route of their own

**Decision.** A file uploaded from the onboarding screen travels, base64
encoded, in the screen's ordinary call to Odoo (`mfi_lending_command`,
`upload_file`). Odoo then:
1. checks the type (JPEG, PNG or PDF) and the size (10 MB, proposed);
2. asks the lending service for an upload address;
3. sends the file there;
4. reports it sent.

The file is never written to Odoo's database or filestore on the way. The
address must be HTTPS, on a host listed in the settings, and receives no token
of ours.

**Why.**
- No extra HTTP route to secure.
- The person's session and rights apply as for every other command.
- The vault is the document's home (architecture §2).
- A browser-direct upload to the vault would need the vault to accept Odoo's origin, which is not in the contract (Q-04).

## D-016 · Service account by client secret for now; signed client assertion is the target

**Decision.** The `service_account` mode signs in with the `odoo` client's
secret, read from `odoo.conf` or the environment.

**Why.** It works with Keycloak as configured today, without key handling in
Odoo.

**Consequences.**
- access-keycloak §4 asks service accounts to use a signed client assertion, with the key in OpenBao.
- That change is tracked as LA-44. It touches only `services/auth.py`.
