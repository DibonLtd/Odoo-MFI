# Odoo-MFI

Dibon's Odoo 19 Enterprise add-ons for microfinance, deployed on Odoo.sh.

## Layout

| Path | What |
|---|---|
| `server-auth/` | OCA server-auth, branch 19.0, as a git submodule. Provides `auth_oidc` (Keycloak sign-in) |
| `requirements.txt` | Python packages Odoo.sh installs on build (`python-jose` for `auth_oidc`) |
| `mfi_loan/` | Microfinance Loans (prototype): clients, loan applications, approvals, disbursement, repayments |
| `mfi_loan_demo/` | Kenyan sample data for `mfi_loan`; install to load it, uninstall to remove it |
| `tools/sso_setup.py` | Sets up the Keycloak provider and links users, per database |

Custom modules go at the repository root, beside `server-auth/`.

## Microfinance Loans (`mfi_loan`), prototype

Replaces the Roan Capital loan portal (roan-loan-app.vercel.app) with screens
inside Odoo, following the portal's rules as its code has them. **Prototype:**
loans are stored in Odoo; the target design keeps them in Kapu Core
(Fineract) behind the lending service, with Odoo as the interface only, so
moving to it is a migration.

**Roles** (Settings → Users → Microfinance; one person may hold several),
with the portal's permissions (`mfi_loan/models/rules.py`):

| Action | Who |
|---|---|
| Capture and edit applications, client documents | Super Admin, Head Office, Credit Manager, Loan Officer |
| Blacklist a client (with a reason) | Super Admin, Head Office, CEO, Credit Manager |
| Approve or reject a stage | The stage's role (Credit Manager, Credit Manager, CEO), or Super Admin |
| Disburse | Super Admin, Finance, Head Office; never the application's creator, unless Super Admin |
| Record and match payments, settle early | Super Admin, Head Office, Credit Manager, Finance, Collections, Loan Officer |
| Reverse a payment | Super Admin, CEO, Head Office, Finance |
| Write off | Super Admin, CEO |
| View a client's personal details (password again, logged) | Every role |
| Audit log | Super Admin, CEO, Head Office, Auditor |
| Everything read-only | Auditor (and every role) |

**The loan's path:**

1. *Draft*: client, loan type, amount, term; guarantor (name, ID, phone);
   security: chattel items and their location, the vehicle (registration,
   make, model, year) or the land (title number, location, registered owner).
2. *Send to officer* → *Pending information*: refused while the client's
   documents (ID and passport photo, or a business's registration and
   director's ID; 6 months of M-Pesa or bank statements), the guarantor or
   the security are missing.
3. *Send for approval*: refused, with what is outstanding, until the loan's
   documents (logbook, NTSA report and valuation; title deed and valuation;
   or the chattels mortgage agreement), the generated agreement, the signed
   agreement, the house visit and, on a first loan, the upfront fee
   reference are in.
4. *Approval*: Credit Manager, Credit Manager, CEO. Nobody decides an
   application they created or acts on it twice. A rejection needs a
   reason; a rejected loan can be reopened.
5. *Disburse* → *Active*: M-Pesa, bank or cash with its reference; a daily
   schedule from the next day, each instalment the daily amount and the last
   the remainder.
6. *Repayments*: each M-Pesa or bank payment needs a reference, never used
   twice. Money pays default interest first, then instalments oldest first.
   A payment with no loan is found by loan S/N, the client's ID number or
   phone, or stays *unmatched* until matched. A reversal re-applies the
   loan's other payments from the start. All paid → *Repaid*.
7. *Default interest*: each day, 1% of every instalment past due and
   unpaid. *In arrears*: instalments due before today unpaid; *overdue*: past
   maturity with a balance; DPD from the oldest unpaid instalment. Charged
   and refreshed daily.
8. *Early settlement*: interest for the days since the first instalment
   (at least 14, at most the term), less what is paid, plus default interest
   due; the future instalments are dropped.
9. *Write-off* (with a reason) closes an active loan.

**Pricing** (Configuration, Super Admin): three loan types at 1% a day,
KES 3,000 to 100,000, 14 or 30 days; interest = principal × rate × days;
daily instalment = total ÷ days, rounded up. Fees: membership 100 (first loan),
application 500 or 1,000 (paid upfront on a first loan), LIF 200,
remittance 120, chattels mortgage 500 or 1,000 (chattels loans), deducted
from the payout.

**Messages:** the reminder SMS goes through Odoo SMS, so it uses whatever
gateway the database has: Odoo IAP credits, or an SMS gateway module such as
Dibon's `dibon_sms`. It can go out each morning to every client in arrears
(Settings). WhatsApp works as on the portal: a wa.me link opens WhatsApp with
the message filled in. The agreement is emailed as a PDF from the company
address, sent by WhatsApp (the officer attaches the PDF), or marked as handed
over.

**Placeholders:** M-Pesa and the bank (references typed in); the agreement
has prototype wording and is signed on paper until Odoo Sign; Keycloak
sign-in is set up separately (below).

**Sample data** (`mfi_loan_demo`, any database, live ones included): install
the app *Microfinance Loans: sample data* to load 30 Kenyan clients (26
individuals and 4 businesses across Kenya), 35 loans in every state spread
over the last three months, daily M-Pesa repayments, arrears in every ageing
bucket, an early settlement, a write-off, a reversed payment, unmatched
payments, and collections notes and promises. Each step was done by the
sample staff through the real workflow and is dated on its day. Nine sample
staff accounts, one per role, sign in as admin@, credit@, credit2@,
headoffice@, ceo@, finance@, officer@, collections@ and
auditor@demo.roancapital.co.ke with a password made at install, shown in
Settings → Microfinance. Where the apps are installed it also loads, each
marked "(sample)": Employees (the eight positions in six departments, twelve
staff with their managers, linked to the sample accounts); CRM (a "Loan
enquiries" team with leads from walk-ins, calls, referrals, field agents,
Facebook and the Request a Loan page: open with a call booked, won into
clients, lost with a reason); Helpdesk (a "Client care" team, complaints,
queries and requests on sample clients, with SLAs to acknowledge within 7
days and resolve within 30, CBK reg 40); and Accounting (the fees of every
disbursed sample loan invoiced and paid by M-Pesa, three months of supplier
bills, some still open, all in sample journals of their own, so real
numbering is untouched). The sample staff get access to those apps. Sample clients never get SMS, WhatsApp or email
(their addresses are @example.com). Uninstall the app to delete all of it,
staff accounts and their audit entries included; loan and client numbering
restarts at 1 if nothing real was numbered meanwhile.

**Screens** (the portal's navigation):

- *Dashboard*: active loans and outstanding; in arrears and missed
  instalments; overdue and to recover; PAR 1, 7 and 30; collected against
  due today; disbursed and collected this month; awaiting action; clients
  and new this month; 30-day collection rate; ageing buckets; the largest
  late balances; the approval queue. Worked out when opened.
- *Clients*: personal details (ID number, phones, email, KRA PIN, bank
  account, contact person, next of kin, guarantors) are masked; *View
  personal details* asks for the user's password again, shows them for 60
  seconds and records the view; five wrong passwords lock it for five
  minutes. Onboarding as the portal asks: individual or business; ID or
  registration number (format checked, never twice), phone (used to match
  M-Pesa), email, KRA PIN (format checked); addresses, business, bank;
  financials (daily income, stock, 6-month M-Pesa and bank cash flow,
  loans elsewhere); a business's director / contact person; next of kin;
  documents. Numbered RC-C-00001.
- *Recovery*: repayments; unmatched payments; collections: late loans
  (masked phones, an Unlock that is recorded, the reminder SMS to send or
  open in WhatsApp, for one loan or a selection, a contact log of calls,
  visits, messages and promises to pay; also on the loan's Collections
  tab), promises to pay (kept or broken), due today, collected.
- *Insights*: the six reports (active portfolio, arrears and overdue
  ageing, disbursements, collections, income summary, clients onboarded),
  each a list to export to Excel or CSV, and the income summary on screen;
  the audit log: every sign-in and failed sign-in, application step,
  approval, disbursement, payment, reversal, settlement, write-off, client
  change (which fields, not the values), document, view of personal
  details, message and settings change, with user, time and IP address.
  Nobody can change or delete an entry.
- *Administration* (Super Admin): Settings (company, repayment and payout
  channels, automatic reminder SMS, sign-in security, fees upfront on a
  first loan; Odoo administrators only), loan types, fees, users and roles.

**Sign-in security**, as on the portal: sign out after 60 idle minutes and
after 10 hours, set on install and changed in Settings (0 switches either
off). They apply to every user of the database. Two-factor authentication:
General Settings → Permissions → *Enforce two-factor authentication* for
employees.

Loans are numbered RC-L-000001.

**Not in the prototype yet:** M-Pesa and bank feeds (payments are typed in);
e-signature (Odoo Sign).

**Tests:** `mfi_loan/tests`, run by Odoo.sh on development and staging builds.

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
