"""The lending screens in a real browser, answered by the stub's own examples."""

from odoo.tests import HttpCase, tagged

from .test_lending import LendingSetup

SCREEN_CHECK = """
(async () => {
    const wait = async (test, what) => {
        for (let i = 0; i < 200; i++) {
            const found = test();
            if (found) { return found; }
            await new Promise((r) => setTimeout(r, 100));
        }
        throw new Error("not found: " + what);
    };
    const $ = (sel) => document.querySelector(sel);
    const byText = (sel, text) => [...document.querySelectorAll(sel)].find((e) => e.textContent.includes(text));
    %s
    await document.fonts.ready;
    const wide = [...document.querySelectorAll(".oi[data-icon]")].filter((e) => {
        const glyph = parseFloat(getComputedStyle(e, "::before").width);
        return glyph > parseFloat(getComputedStyle(e).fontSize) * 1.8;
    }).map((e) => e.dataset.icon);
    if (wide.length) { throw new Error("icons drawn as text: " + wide.join(", ")); }
    console.log("test successful");
})();
"""

ONBOARDING = """
    await wait(() => byText(".card-header", "Checklist"), "checklist");
    await wait(() => byText("li", "Phone confirmed"), "checklist item");
    if (!byText(".badge", "Draft")) { throw new Error("state badge"); }
    if (!byText(".o_mfi_lending", "•••••670")) { throw new Error("masked ID"); }
    if (byText("button", "Submit") && !byText("button", "Submit").disabled) {
        throw new Error("submit offered though not in actions");
    }
    byText("button", "Send code").click();
    await wait(() => byText(".o_notification", "Code sent"), "code sent notification");
    const input = $("input[inputmode=numeric]");
    input.value = "12";
    input.dispatchEvent(new Event("input"));
    byText("button", "Confirm").click();
    await wait(() => byText(".o_mfi_lending_error", "6 digits"), "local code check");
"""

CLIENTS = """
    await wait(() => byText("td", "Amani"), "live list row");
    if (!byText(".badge", "Under review")) { throw new Error("held badge"); }
"""

PUSH = """
    await wait(() => byText(".o_mfi_lending_push", "In the lending service"), "pushed row");
    await wait(() => byText(".o_mfi_lending_push", "consent"), "refused row with reason");
"""


@tagged("post_install", "-at_install")
class TestLendingUi(LendingSetup, HttpCase):

    def setUp(self):
        super().setUp()
        self.transport = self.stub()

    def _client_action(self, tag, params):
        action = self.env["ir.actions.client"].create({"name": "Lending test", "tag": tag, "params": params})
        return f"/odoo/action-{action.id}"

    def _run(self, url, steps):
        self.browser_js(url, SCREEN_CHECK % steps, login="mfi_officer", timeout=120)

    def test_onboarding_screen(self):
        self.amani.mfi_lending_push()
        self._run(self._client_action("mfi_loan.lending_onboarding", {"partner_id": self.amani.id}), ONBOARDING)
        self.assertTrue([c for c in self.transport.calls if c["url"].endswith("/phone-verification")])

    def test_live_clients_list(self):
        self._run(self._client_action("mfi_loan.lending_clients", {}), CLIENTS)

    def test_bulk_push_dialog(self):
        ids = (self.amani | self.client).ids
        self._run(self._client_action("mfi_loan.lending_push", {"ids": ids}), PUSH)
        self.assertEqual(self.amani.mfi_lending_sync, "in_backend")
        self.assertEqual(self.client.mfi_lending_sync, "local")
