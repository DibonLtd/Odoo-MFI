{
    "name": "Kapu lending connector",
    "version": "20.0.0.1.0",
    "summary": "Calls the Kapu lending staff API: settings, sign-in, errors, and a command log with idempotency keys",
    "description": """
The connection between Odoo and the Kapu lending service (staff API, slice 1:
individual onboarding). It holds no business rule and depends on base and web
only, so it runs on Odoo Community too. Secrets come from odoo.conf or the
environment, never the database. See docs/lending-api/ in the repository.
""",
    "category": "Accounting/Microfinance",
    "author": "Dibon",
    "license": "LGPL-3",
    "depends": ["base", "web", "base_setup"],
    "data": [
        "security/ir.access.csv",
        "data/ir_cron.xml",
        "views/lending_command_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
}
