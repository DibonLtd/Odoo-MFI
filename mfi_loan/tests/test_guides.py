from odoo.tests import tagged

from .common import MfiCase


@tagged("post_install", "-at_install")
class TestGuides(MfiCase):
    """Page guides, the loan's Next step box and the dashboard panels."""

    def test_guides_point_at_real_actions(self):
        """Every guide's menu action and button resolves (a typo would hide it)."""
        for guide in self.env["mfi.guide"].search([]):
            if guide.action_xmlid:
                self.assertTrue(self.env.ref(guide.action_xmlid, raise_if_not_found=False), guide.name)
            for button in guide.button_ids:
                self.assertTrue(self.env.ref(button.action_xmlid, raise_if_not_found=False),
                                f"{guide.name}: {button.label}")
            self.assertIn(guide.model, self.env, guide.name)

    def test_user_sees_guides_and_can_hide_one(self):
        guides = self.env["mfi.guide"].with_user(self.officer).mfi_get_guides()
        self.assertTrue(guides)
        loan_list = next(g for g in guides if g["model"] == "mfi.loan" and g["view_type"] == "list"
                         and g["action_id"] == self.env.ref("mfi_loan.action_mfi_loan").id)
        self.assertTrue(loan_list["buttons"])

        self.env["res.users"].with_user(self.officer).mfi_hide_guide(loan_list["id"])
        ids = [g["id"] for g in self.env["mfi.guide"].with_user(self.officer).mfi_get_guides()]
        self.assertNotIn(loan_list["id"], ids)
        # other users still see it
        ids = [g["id"] for g in self.env["mfi.guide"].with_user(self.cm1).mfi_get_guides()]
        self.assertIn(loan_list["id"], ids)

        self.officer.with_user(self.officer).action_mfi_reset_guides()
        ids = [g["id"] for g in self.env["mfi.guide"].with_user(self.officer).mfi_get_guides()]
        self.assertIn(loan_list["id"], ids)

    def test_guides_switch_off(self):
        settings = self.env["res.config.settings"].create({"mfi_show_guides": False})
        settings.execute()
        self.assertFalse(self.env["mfi.guide"].mfi_get_guides())
        self.assertFalse(self.env["res.config.settings"].create({}).mfi_show_guides)
        loan = self._new_loan()
        self.assertFalse(loan.next_step_html)

        self.env["res.config.settings"].create({"mfi_show_guides": True}).execute()
        self.assertTrue(self.env["mfi.guide"].mfi_get_guides())

    def test_next_step_follows_the_loan(self):
        loan = self._new_loan()
        self.assertIn("Step 1 of 5", loan.next_step_title)
        self.assertEqual(loan.next_step_tone, "info")
        self.assertIn("alert-info", loan.next_step_html)

        self._ready(loan)
        self.assertIn("Step 3 of 5: waiting", loan.with_user(self.officer).next_step_title)
        self.assertIn("Step 3 of 5: your decision", loan.with_user(self.cm1).next_step_title)

        loan.with_user(self.cm1).action_approve()
        loan.with_user(self.cm2).action_approve()
        loan.with_user(self.ceo).action_approve()
        self.assertIn("Step 4 of 5", loan.next_step_title)

        loan.with_user(self.finance).action_disburse("mpesa", "NXT1")
        self.assertIn("Step 5 of 5", loan.next_step_title)
        self.assertEqual(loan.next_step_tone, "success")

    def test_dashboard_panels(self):
        self._active(self._new_loan(), days_ago=10)
        board = self.env["mfi.dashboard"].with_user(self.ceo).create({})
        self.assertIn("PAR 30", board.risk_html)
        self.assertIn("o_mfi_bar", board.ageing_html)
        self.assertIn("o_mfi_badge", board.attention_html)
        for method in ("action_open_overdue", "action_open_pending_information", "action_open_to_disburse",
                       "action_open_disbursed_month", "action_open_clients", "action_open_collected_today",
                       "action_open_collected_month", "action_open_due_today"):
            self.assertEqual(getattr(board, method)()["type"], "ir.actions.act_window", method)
