# Task list: Microfinance in Odoo over the Kapu lending API

The work to move `mfi_loan` onto the Kapu lending service, slice by slice.
Decisions are in [DECISIONS.md](DECISIONS.md); the state of play, how to run
it, and the open questions are in [HANDOFF.md](HANDOFF.md).

## How to use this list

**Ticking off a task.**
- A task is ticked only when its acceptance holds and its tests pass on a fresh Odoo 20 database.
- When you tick a task, note the commit and date: `- [x] LA-10 … (abc1234, 2026-11-26)`.

**Blocked by.** A task is blocked by:
- an **API** slice not yet provided;
- **Keycloak** (sign-in, or token exchange);
- or a **Q-xx**, an open question for the backend team (HANDOFF.md §6).

**Until a feature's API exists,** it stays as local Odoo records, working as
today (D-001).

**Adding a task.** Give it the next free number in its phase. Never reuse a
number.

## Status

| Phase | What | State |
|---|---|---|
| 0 | Planning documents | Done |
| 1 | The connector (`mfi_lending_api`) | Done, except running the live-stub test (LA-17) and the session token (LA-12, via LA-41) |
| 2 | Local capture and push | Done |
| 3 | The onboarding screen | Done, except guides for the new screens (LA-37) |
| 4 | Production authentication | Blocked: Keycloak |
| 5 | Hardening | In progress: LA-50 and LA-54 done |
| 6+ | Later slices | Blocked: API |

---

## Phase 0 · Planning

- [x] **LA-01** DECISIONS.md, TASKLIST.md and HANDOFF.md in `docs/lending-api/`; linked from README.md.
- [x] **LA-02** API contract and stub kept in `Requirements/` (`kapu-lending.v1.yaml` 1.0.0-draft.1, `lending.json`).

## Phase 1 · The connector: `mfi_lending_api` (D-002)

- [x] **LA-10** Addon skeleton. (uncommitted, 2026-11-25)
  - Depends on `base` and `web` only.
  - Installs on a fresh Odoo 20 database.
  - Security file present.
- [x] **LA-11** Settings. (uncommitted, 2026-11-25)
  - Enabled, base URL, auth mode, Keycloak token URL, client id, audience, timeouts, and the stub example header (static mode only).
  - Secrets from `odoo.conf` or the environment only (D-005).
  - *Acceptance:* no secret is in `ir_config_parameter`; a test asserts it.
- [ ] **LA-12** Token providers: `static`, `service_account` (client credentials), and an interface for `token_exchange` (D-005).
  - *Acceptance:* the service-account token is cached in memory until expiry and never stored.
  - *Progress:* `static`, `service_account` and the exchange call itself are built and tested. The person's token reaching the session is LA-41.
- [x] **LA-13** `LendingClient`: all 13 slice-1 operations (`listClients`, `createClient`, `getClient`, `updateClient`, `sendPhoneCode`, `confirmPhoneCode`, `listDocuments`, `requestDocumentUpload`, the PUT to the upload address, `completeDocumentUpload`, `sendUploadLink`, `submitClient`, `getVerifications`). (uncommitted, 2026-11-25)
  - Headers: `Idempotency-Key`, `If-Match`, merge-patch content type.
  - Timeouts: 5 s connect, 15 s read.
  - A missing key is treated as `null`.
  - *Acceptance:* every operation is tested against the stub's examples.
- [x] **LA-14** Errors (D-012). (uncommitted, 2026-11-25)
  - Problem details become `LendingRefusal` (code, field, `traceId`, extras such as `existingClientId`, `missingDocuments`, `retryAfterSeconds`).
  - Network errors and 5xx become `LendingUnavailable`.
  - English and Swahili text for all 21 refusal codes.
  - *Acceptance:* each code is mapped and tested.
- [x] **LA-15** Command log and idempotency store, `mfi.lending.command` (D-006). (uncommitted, 2026-11-25)
  - Same body hash: the key is reused. Changed body: a new key.
  - `request_in_progress`: retried with the same key.
  - *Acceptance:* no body and no personal data stored; tested.
- [x] **LA-16** Test connection button: `GET /v1/clients?limit=1`, reporting success or the refusal. (uncommitted, 2026-11-25)
- [ ] **LA-17** Test support.
  - A mock transport answering from `lending.json` by `X-Stub-Example`.
  - Optional tests against a running stub (`KAPU_LENDING_STUB_URL`), tagged `lending_stub`.
  - *Progress:* the mock transport is done. The live-stub test is written (`mfi_lending_api/tests/test_stub_live.py`) but not yet run: no WireMock image was reachable on 2026-11-25.

## Phase 2 · Local capture and push (D-003, D-004, D-009, D-010, D-011)

- [x] **LA-20** Client fields the API needs. (uncommitted, 2026-11-25)
  - First, middle and last name (the client's name composed from them).
  - ID type (national ID, alien ID, passport).
  - Date of birth.
  - Consent to checks, with when and by whom (never defaulted).
  - County, town, street, landmark.
  - Primary next of kin.
  - *Acceptance:* existing clients upgrade without loss; the rules check the new fields.
- [x] **LA-21** Sync fields: lending client id (unique), push outcome (local, in lending service, push failed), pushed at and by. Shown on the form and filterable in the list. (uncommitted, 2026-11-25)
- [x] **LA-22** Field mapping: local fields to `CreateClient` and to the update (merge patch). (uncommitted, 2026-11-25)
  - Phone to E.164.
  - Document kinds to API types, in one place (`DOCUMENT_TYPES`, D-014).
- [x] **LA-23** Local checks before a push, each refused with a reason and no call: (uncommitted, 2026-11-25)
  - a business client (D-010);
  - consent not recorded;
  - no date of birth or ID type;
  - blacklisted;
  - a document not jpeg, png or pdf.
- [x] **LA-24** Push one client: create, then update the contact details (with a fresh ETag), then upload the held documents (request, PUT, complete). (uncommitted, 2026-11-25)
  - On `client_already_exists`, link to `existingClientId` if no other client holds it.
  - Audited.
- [x] **LA-25** **Create in lending service** button on the client form. (uncommitted, 2026-11-25)
  - Shown to Super Admin, Head Office, Credit Manager and Loan Officer (`lending.push`).
- [x] **LA-26** Bulk push from the client list: a progress dialog, one call per selected client in the person's own session, a result for each; safe to run again (D-011). (uncommitted, 2026-11-25)
- [x] **LA-27** After a push, the onboarding fields are read-only locally. Contact changes go through the API, and the local copy is updated (D-004). (uncommitted, 2026-11-25)
- [x] **LA-28** Local document file deleted once the lending service reports it `STORED`; a note says where it is (D-004). (uncommitted, 2026-11-25)

## Phase 3 · The onboarding screen (D-007, D-008)

- [x] **LA-30** Onboarding screen for one client. (uncommitted, 2026-11-25)
  - Live, masked details; the checklist; "fetched at".
  - Buttons only from `actions`.
- [x] **LA-31** Edit contact details (email, address, next of kin, business, phone): PATCH with `If-Match`; on 412, re-read and say what changed. (uncommitted, 2026-11-25)
- [x] **LA-32** Phone: send the code, with the `resendAfter` countdown and `Retry-After` on 429; confirm the 6-digit code; `code_incorrect` and `code_expired` explained. (uncommitted, 2026-11-25)
- [x] **LA-33** Documents: list with states and rejection reasons. Upload from the screen: the file passes through Odoo to the upload address and is never stored. Send an upload link by SMS or email. (uncommitted, 2026-11-25)
- [x] **LA-34** Submit: `phone_not_confirmed` and `documents_missing` (naming them) explained; then `VERIFYING`. (uncommitted, 2026-11-25)
- [x] **LA-35** Verifications. (uncommitted, 2026-11-25)
  - Polled while `VERIFYING`.
  - `CORRECTION_NEEDED` names the field.
  - `HELD` shows nothing more (no tipping off, JN-02 §3 a).
  - `VERIFIED` and `ACTIVE` shown, with the tier.
- [x] **LA-36** "Lending service clients": a live list with a state filter and cursor paging; each row opens its local client when linked. (uncommitted, 2026-11-25)
- [ ] **LA-37** Guides (the green "What to do here" box) for the new screens.

## Phase 4 · Production authentication (D-005)

- [ ] **LA-40** Keycloak sign-in to Odoo through OCA `auth_oidc` on Odoo 20, unmodified (access K10). **Blocked by:** OCA `server-auth` 20.0; Keycloak `odoo` client.
- [ ] **LA-41** Token exchange: the person's token taken from the session (never from the user record, K15) and exchanged for audience `lending-service`; the exchanged token is held in the session until it expires. **Blocked by:** LA-40; Keycloak exchange permission for `odoo`.
- [ ] **LA-42** Odoo roles from Keycloak groups, Roan Capital's eight positions (staff-workspace §4, FS-979). **Blocked by:** LA-40; Roan Capital's role list (open answer 7).
- [ ] **LA-43** No local passwords for staff once sign-in through Keycloak is live (staff-workspace §6). **Blocked by:** LA-40.
- [ ] **LA-44** Service account by signed client assertion, with the key from OpenBao, instead of a client secret (access-keycloak §4, D-016). **Blocked by:** OpenBao in the instance.

## Phase 5 · Hardening

- [x] **LA-50** Command log cleaned after 13 months (scheduled action). (uncommitted, 2026-11-25)
- [ ] **LA-51** Metrics: commands by outcome, the lending service's response time as Odoo sees it; an alert when commands fail above 2 % in 15 minutes (staff-workspace §8). **Blocked by:** observability stack.
- [ ] **LA-52** Every new label and message in Swahili (`sw.po`).
  - *Progress:* the connector's refusal texts are in Swahili (`mfi_lending_api/i18n/sw.po`), to be reviewed by Roan Capital. The onboarding screen's labels are not done.
- [ ] **LA-53** Security review: no personal data in logs or the command log; no token in the database; the PUT goes only to the host the API named.
  - *Progress:* tests check that no personal data reaches the command log, no secret reaches settings, and uploads go only to allowed hosts with no token. Still open: a review by someone other than the author.
- [x] **LA-54** Headless browser test of the onboarding screen and the bulk push against the stub. (uncommitted, 2026-11-25)
- [ ] **LA-55** A screen opens within 2 seconds at the 95th percentile against the stub (staff-workspace §8).

## Phase 6 and later · Slices still to come

Each stays as **local Odoo records until its API exists** (D-001). Each moves
in three steps: add the operations to the connector, switch the screen to live
reads and commands, then migrate or retire the local records.

- [ ] **LA-60** Loan applications: capture, submit, documents and security. **Blocked by:** API slice (applications). Supersedes D-013.
- [ ] **LA-61** My tasks and approvals: through the approval engine, with step-up at each decision (staff-workspace rule 3). **Blocked by:** approval engine API; Keycloak step-up.
- [ ] **LA-62** Payouts. **Blocked by:** API slice (disbursement); rails events.
- [ ] **LA-63** Repayments and unplaced payments (JN-16). **Blocked by:** API slice (repayments).
- [ ] **LA-64** Arrears and the collection ladder. **Blocked by:** lender rules API.
- [ ] **LA-65** Products and product versions (draft, preview, adopt, submit). **Blocked by:** lender rules API.
- [ ] **LA-66** Partners. **Blocked by:** API slice (partners).
- [ ] **LA-67** Guarantors (JN-05). **Blocked by:** API slice.
- [ ] **LA-68** Reveal personal data with step-up (`/reveal`, 501 in slice 1). **Blocked by:** Q-03.
- [ ] **LA-69** Lead conversion: a CRM lead becomes a client with `leadRef` (staff-workspace rule 5). **Blocked by:** whether CRM joins the module's dependencies.
- [ ] **LA-70** Business clients onboarded through the API. **Blocked by:** API slice (business clients).
- [ ] **LA-71** Dashboard figures from the API, not local loans. **Blocked by:** LA-60 to LA-64.
- [ ] **LA-80** Purge the temporary local copy of personal data (closes the D-004 deviation). **Blocked by:** LA-60, LA-63, LA-64, or LA-68.
- [ ] **LA-81** Existing local clients onboarded: through the bulk push (LA-26), or an import path if the backend provides one. **Blocked by:** Q-09.
