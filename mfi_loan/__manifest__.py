{
    "name": "Microfinance Loans (prototype)",
    "version": "19.0.0.3.0",
    "summary": "Clients, loan applications, approvals, disbursement and repayments for a lender",
    "description": """
Prototype that replaces the Roan Capital loan portal with screens inside Odoo.
Loans are stored in Odoo for now; the target design keeps them in Kapu Core
(Fineract) behind the lending service, with Odoo as the interface only.
Bank and M-Pesa are placeholders: references are typed in. SMS goes through
Odoo SMS; WhatsApp opens a wa.me link. Sample data: the mfi_loan_demo module.
""",
    "category": "Accounting/Microfinance",
    "author": "Dibon",
    "license": "LGPL-3",
    "depends": ["mail", "contacts", "sms", "auth_totp_mail"],
    "data": [
        "security/mfi_security.xml",
        "security/ir.model.access.csv",
        "data/mfi_data.xml",
        "wizard/mfi_loan_wizard_views.xml",
        "wizard/mfi_report_wizard_views.xml",
        "report/mfi_loan_agreement.xml",
        "data/mfi_mail_data.xml",
        "wizard/mfi_reveal_wizard_views.xml",
        "views/mfi_loan_views.xml",
        "views/mfi_payment_views.xml",
        "views/mfi_collection_views.xml",
        "views/mfi_config_views.xml",
        "views/mfi_settings_views.xml",
        "views/res_partner_views.xml",
        "views/mfi_dashboard_views.xml",
        "views/mfi_audit_views.xml",
        "views/mfi_menus.xml",
    ],
    "application": True,
    "installable": True,
}
