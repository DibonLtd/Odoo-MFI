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

    def test_live_dashboard_data(self):
        late = self._active(self._new_loan(), days_ago=10)  # 9 days late
        self._pay(late, 500, "DASH1")
        Board = self.env["mfi.dashboard"].with_user(self.ceo)
        for period in ("today", "7d", "30d", "month", "year"):
            data = Board.mfi_dashboard_data(period)
            self.assertEqual(data["period"], period)
            self.assertEqual(len(data["series"]["labels"]), len(data["series"]["collected"]), period)
            self.assertGreaterEqual(len(data["series"]["labels"]), 7, period)  # always at least a week
        data = Board.mfi_dashboard_data("30d")
        self.assertEqual(data["kpis"]["collected"]["value"], 500)
        self.assertEqual(data["kpis"]["disbursed"]["count"], 1)
        self.assertEqual(data["book"]["active"]["count"], 1)
        self.assertEqual([loan["id"] for loan in data["late"]], [late.id])
        self.assertEqual(sum(b["count"] for b in data["ageing"]), 1)
        self.assertEqual(data["payments"][0]["amount"], 500)

    def test_how_it_works_data(self):
        """The How it works page reads loan types, fees and loans per state, and opens each state."""
        self._active(self._new_loan(), days_ago=3)
        Board = self.env["mfi.dashboard"].with_user(self.officer)
        data = Board.mfi_how_it_works_data()
        states = {s["key"]: s["count"] for s in data["states"]}
        self.assertEqual(set(states), {"draft", "pending_information", "pending_approval", "approved",
                                       "active", "repaid", "rejected", "written_off"})
        self.assertGreaterEqual(states["active"], 1)
        self.assertTrue(data["products"])
        self.assertTrue(data["fees"])
        self.assertTrue(data["sample"])  # a loan to open at the end of the demo
        for key in states:
            action = Board.mfi_dashboard_action(key)
            self.assertEqual(action["context"], {f"search_default_{key}": 1})
        self.assertTrue(self.env.ref("mfi_loan.action_mfi_how_it_works"))

    def test_live_dashboard_drilldown(self):
        Board = self.env["mfi.dashboard"].with_user(self.ceo)
        for key, value in [("collected", None), ("disbursed", None), ("rate", None), ("clients", None),
                           ("applications", None), ("active", None), ("arrears", None), ("overdue", None),
                           ("pending_information", None), ("pending_approval", None), ("approved", None),
                           ("health", "current"), ("health", "overdue"), ("ageing", "1_7"), ("mine", None),
                           ("late", None), ("payments", None)]:
            action = Board.mfi_dashboard_action(key, "30d", value)
            self.assertEqual(action["type"], "ir.actions.act_window", key)
            domain = action.get("domain") or []
            if isinstance(domain, list):  # ours; menu actions keep their own (text) domain
                self.env[action["res_model"]].with_user(self.ceo).search(domain)
