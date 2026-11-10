{
    "name": "Microfinance Loans: sample data",
    "version": "19.0.0.2.0",
    "summary": "Kenyan sample data for Microfinance, CRM, Helpdesk, Employees and Accounting; uninstall to remove it",
    "description": """
Loads sample data into any database, live ones included, so the Microfinance
screens can be shown with realistic Kenyan data: about 30 clients (individuals
and businesses across Kenya), loans in every state spread over the last three
months, daily M-Pesa repayments, arrears in every ageing bucket, collections
notes and promises, and nine staff accounts, one per role.

Where these apps are installed, it also loads: Employees (Roan Capital's
eight positions in six departments, twelve staff with managers); CRM (loan
enquiries from walk-ins, calls, referrals, field agents, Facebook and the
Request a Loan page, open, won and lost); Helpdesk (complaints and queries
with the CBK 30-day clock); and Accounting (loan fee invoices paid by M-Pesa,
three months of supplier bills, in sample journals of their own).

Everything is created through the real workflow. Sample clients never receive
SMS, WhatsApp or email. Uninstalling this module deletes every sample record,
the staff accounts included.
""",
    "category": "Accounting/Microfinance",
    "author": "Dibon",
    "license": "LGPL-3",
    "depends": ["mfi_loan"],
    "data": [
        "data/mfi_demo_data.xml",
        "views/res_config_settings_views.xml",
    ],
    "uninstall_hook": "uninstall_hook",
    "installable": True,
}
