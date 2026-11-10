from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSampleData(TransactionCase):

    def test_loaded(self):
        env = self.env
        clients = env["res.partner"].search([("mfi_is_sample", "=", True)])
        self.assertEqual(len(clients), 30)
        self.assertTrue(all(c.mfi_client_no and c.mfi_documents_complete for c in clients))
        loans = env["mfi.loan"].search([("partner_id", "in", clients.ids)])
        states = set(loans.mapped("state"))
        self.assertTrue({"draft", "pending_information", "pending_approval", "approved", "active",
                         "repaid", "rejected", "written_off"} <= states, states)
        buckets = set(loans.filtered(lambda loan: loan.state == "active").mapped("ageing_bucket"))
        self.assertTrue({"current", "1_7", "8_14", "15_30", "30_plus"} <= buckets, buckets)
        self.assertTrue(env["mfi.payment"].search_count([("state", "=", "unmatched")]) >= 2)
        self.assertTrue(env["mfi.payment"].search_count([("state", "=", "reversed")]) >= 1)
        self.assertTrue(env["mfi.collection.note"].search_count([("loan_id", "in", loans.ids)]))
        staff = env["res.users"].search([("login", "=like", "%@demo.roancapital.co.ke")])
        self.assertEqual(len(staff), 9)
        self.assertTrue(env["ir.config_parameter"].get_param("mfi_loan_demo.password"))
        board = env["mfi.dashboard"].create({})
        self.assertGreater(board.par_1, 0)
        self.assertTrue(all(c._mfi_messaging_blocked() for c in clients))

    def test_dated_history(self):
        loans = self.env["mfi.loan"].search([("partner_id.mfi_is_sample", "=", True), ("state", "=", "repaid")])
        self.assertTrue(loans)
        for loan in loans:
            self.assertLess(loan.create_date.date(), loan.disbursed_date)
            self.assertTrue(loan.closed_date <= loan.maturity_date)

    def test_other_apps(self):
        env = self.env
        if "hr.employee" in env:
            employees = env["hr.employee"].search([("department_id.name", "like", "(sample)")])
            self.assertEqual(len(employees), 12)
            self.assertEqual(len(employees.user_id), 9)
            ceo = employees.filtered(lambda e: e.name == "Daniel Mwaura")
            self.assertFalse(ceo.parent_id)
            self.assertTrue(all(e.parent_id for e in employees - ceo))
        if "crm.lead" in env:
            Lead = env["crm.lead"].with_context(active_test=False)
            leads = Lead.search([("team_id.name", "=", "Loan enquiries (sample)")])
            self.assertGreaterEqual(len(leads), 19)
            self.assertGreaterEqual(len(leads.filtered(lambda lead: lead.stage_id.is_won)), 8)
            self.assertEqual(len(leads.filtered("lost_reason_id")), 4)
            self.assertTrue(all(leads.filtered(lambda lead: lead.stage_id.is_won).partner_id.mapped("mfi_is_sample")))
        if "helpdesk.ticket" in env:
            tickets = env["helpdesk.ticket"].search([("team_id.name", "=", "Client care (sample)")])
            self.assertEqual(len(tickets), 9)
            self.assertTrue(any(t.sla_deadline for t in tickets))
            oldest = min(tickets.mapped("create_date"))
            self.assertLess(oldest.date(), self.env.cr.now().date())
        if "account.move" in env:
            journal = env["account.journal"].search([("name", "=", "Loan fees (sample)")])
            if journal:  # a database with a chart of accounts
                invoices = env["account.move"].search([("journal_id", "=", journal.id)])
                self.assertTrue(invoices)
                self.assertTrue(all(i.state == "posted" and i.payment_state in ("paid", "in_payment")
                                    for i in invoices))
                bills = env["account.move"].search([("journal_id.name", "=", "Supplier bills (sample)")])
                self.assertEqual(len(bills), 21)
                self.assertTrue(bills.filtered(lambda b: b.payment_state == "not_paid"))

    def test_unload_removes_everything(self):
        env = self.env
        clients = env["res.partner"].search([("mfi_is_sample", "=", True)])
        staff = env["res.users"].search([("login", "=like", "%@demo.roancapital.co.ke")])
        env["mfi.demo"]._unload()
        self.assertFalse(clients.exists())
        self.assertFalse(env["mfi.loan"].search_count([]))
        self.assertFalse(env["mfi.payment"].search_count([]))
        self.assertFalse(env["res.users"].search([("id", "in", staff.ids)]))
        self.assertFalse(env["mfi.audit.log"].search_count([("user_id", "in", staff.ids)]))
        self.assertFalse(env["ir.model.data"].search_count([("module", "=", "mfi_loan_demo"),
                                                           ("name", "=like", "sample_%")]))
        self.assertFalse(env["ir.config_parameter"].get_param("mfi_loan_demo.password"))
        if "account.journal" in env:
            self.assertFalse(env["account.journal"].search_count([("name", "like", "(sample)")]))
        if "crm.lead" in env:
            self.assertFalse(env["crm.team"].search_count([("name", "like", "(sample)")]))
        if "helpdesk.team" in env:
            self.assertFalse(env["helpdesk.team"].search_count([("name", "like", "(sample)")]))
        if "hr.employee" in env:
            self.assertFalse(env["hr.department"].search_count([("name", "like", "(sample)")]))
