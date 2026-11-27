# Copyright 2016 ICTSTUDIO <http://www.ictstudio.eu>
# Copyright 2021 ACSONE SA/NV <https://acsone.eu>
# License: AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
# Ported to Odoo 20.0 by Dibon from OCA/server-auth 19.0 (commit 357c210), until OCA
# publishes 20.0: see docs/lending-api/DECISIONS.md D-021 for what changed and why.

{
    "name": "Authentication OpenID Connect",
    "version": "20.0.1.0.0",
    "license": "AGPL-3",
    "author": (
        "ICTSTUDIO, André Schenkels, ACSONE SA/NV, Odoo Community Association (OCA)"
    ),
    "maintainers": ["sbidoul"],
    "website": "https://github.com/OCA/server-auth",
    "summary": "Allow users to login through OpenID Connect Provider",
    "external_dependencies": {"python": ["python-jose"]},
    "depends": ["auth_oauth"],
    "data": ["views/auth_oauth_provider.xml", "data/auth_oauth_data.xml"],
}
