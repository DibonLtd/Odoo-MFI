{
    "name": "Microfinance Loans",
    "version": "20.0.0.6.0",
    "summary": "Clients, loan applications, approvals, disbursement and repayments for a lender",
    "description": """
Roan Capital's lending in Odoo: clients, loan applications, approvals,
disbursement, repayments and collections. Clients are onboarded through the
Kapu lending service; loans are booked in Odoo Accounting (loan invoices with
daily instalments, payments, default interest, follow-up reminders) until they
move to the lending service. SMS goes through Odoo SMS; WhatsApp opens a wa.me
link. Sample data: the mfi_loan_demo module.
""",
    "category": "Accounting/Microfinance",
    "author": "Dibon",
    "license": "LGPL-3",
    "depends": ["mail", "contacts", "sms", "auth_totp_mail", "account_accountant", "account_followup", "mfi_lending_api"],
    "data": [
        "security/mfi_security.xml",
        "security/ir.access.csv",
        "data/mfi_data.xml",
        "data/mfi_accounting_data.xml",
        "wizard/mfi_loan_wizard_views.xml",
        "report/mfi_loan_agreement.xml",
        "data/mfi_mail_data.xml",
        "wizard/mfi_reveal_wizard_views.xml",
        "views/mfi_loan_views.xml",
        "views/mfi_payment_views.xml",
        "views/mfi_collection_views.xml",
        "views/mfi_config_views.xml",
        "views/mfi_guide_views.xml",
        "views/mfi_settings_views.xml",
        "views/res_partner_views.xml",
        "views/mfi_dashboard_views.xml",
        "views/mfi_audit_views.xml",
        "data/mfi_guide_data.xml",
        "views/mfi_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mfi_loan/static/src/**/*",
        ],
    },
    "application": True,
    "installable": True,
}
