{
    "name": "Microfinance Loans (prototype)",
    "version": "19.0.0.1.0",
    "summary": "Clients, loan applications, approvals, disbursement and repayments for a lender",
    "description": """
Prototype that replaces the Roan Capital loan portal with screens inside Odoo.
Loans are stored in Odoo for now; the target design keeps them in Kapu Core
(Fineract) behind the lending service, with Odoo as the interface only.
Bank, M-Pesa and WhatsApp are placeholders: references are typed in.
""",
    "category": "Accounting/Microfinance",
    "author": "Dibon",
    "license": "LGPL-3",
    "depends": ["mail", "contacts"],
    "data": [
        "security/mfi_security.xml",
        "security/ir.model.access.csv",
        "data/mfi_data.xml",
        "wizard/mfi_loan_wizard_views.xml",
        "report/mfi_loan_agreement.xml",
        "views/mfi_loan_views.xml",
        "views/mfi_payment_views.xml",
        "views/mfi_config_views.xml",
        "views/res_partner_views.xml",
        "views/mfi_menus.xml",
    ],
    "demo": ["demo/mfi_demo.xml"],
    "application": True,
    "installable": True,
}
