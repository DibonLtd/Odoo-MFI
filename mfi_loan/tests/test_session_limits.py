"""Session limits over real HTTP: an expired session signs the person out (it
used to crash every page on Odoo 20, where logout is no longer a session method)."""

import time

from odoo.http.session import session_store
from odoo.tests import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestSessionLimits(HttpCase):

    def setUp(self):
        super().setUp()
        params = self.env["ir.config_parameter"].sudo()
        params.set_int("mfi_loan.session_idle_minutes", 60)
        params.set_int("mfi_loan.session_max_hours", 10)
        new_test_user(self.env, login="mfi_session_user", groups="base.group_user,mfi_loan.group_mfi_user")

    def _session(self):
        return session_store().get(self.session.sid, keep_sid=True)

    def test_active_session_is_kept(self):
        self.authenticate("mfi_session_user", "mfi_session_user")
        response = self.url_open("/odoo/action-mfi_loan.action_mfi_loan")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._session().uid)

    def test_idle_session_signs_out(self):
        self.authenticate("mfi_session_user", "mfi_session_user")
        session = self._session()
        session["mfi_seen"] = time.time() - 2 * 3600  # idle for two hours, the limit is one
        session["mfi_started"] = time.time() - 2 * 3600
        session_store().save(session)
        response = self.url_open("/odoo", allow_redirects=False)
        self.assertLess(response.status_code, 500)
        self.assertIn("/web/login", response.headers.get("Location", "") or response.url)

    def test_too_long_session_signs_out(self):
        self.authenticate("mfi_session_user", "mfi_session_user")
        session = self._session()
        session["mfi_started"] = time.time() - 11 * 3600  # signed in eleven hours ago, the limit is ten
        session["mfi_seen"] = time.time()
        session_store().save(session)
        response = self.url_open("/odoo", allow_redirects=False)
        self.assertLess(response.status_code, 500)
        self.assertIn("/web/login", response.headers.get("Location", "") or response.url)
