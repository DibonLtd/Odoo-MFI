import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";

const PLAY_MS = 4500; // how long Play stays on each step of the journey
const reduceMotion = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
const r2 = (n) => Math.round((n + Number.EPSILON) * 100) / 100;

/**
 * The parts of the page, in order: the nav chips at the top jump to them.
 */
const PARTS = [
    { key: "journey", number: 1, title: "The loan's journey", hint: "From application to repaid" },
    { key: "people", number: 2, title: "Who does what", hint: "Roles and approvals" },
    { key: "pricing", number: 3, title: "What a loan costs", hint: "Live calculator" },
    { key: "repay", number: 4, title: "Repayments", hint: "Where each shilling goes" },
    { key: "safe", number: 5, title: "Safeguards", hint: "Privacy and audit" },
    { key: "live", number: 6, title: "Show it live", hint: "Open the real screens" },
];

/**
 * The loan's journey. `state` links a step to the loans in that state (live count);
 * the client step counts clients instead.
 */
const JOURNEY = [
    {
        key: "client", icon: "fa-user-plus", tone: "indigo", title: "Onboard the client",
        who: "Loan Officer, Credit Manager, Head Office",
        say: "Every loan starts with a client, an individual or a business, captured once and reused for every loan.",
        points: [
            "ID or registration number checked for format and never accepted twice",
            "Phone number, used later to match M-Pesa payments",
            "KRA PIN, addresses, business, bank, next of kin",
            "Financials: daily income, stock, 6 months of M-Pesa and bank cash flow, loans elsewhere",
        ],
        button: "Onboard client", open: "mfi_loan.action_mfi_client",
    },
    {
        key: "draft", state: "draft", icon: "fa-pencil-square-o", tone: "cyan", title: "Capture the application",
        who: "Loan Officer, Credit Manager, Head Office",
        say: "The officer picks the client, loan type, amount and term. Odoo prices the loan on the spot: interest, fees and the daily instalment.",
        points: [
            "Guarantor: name, ID and phone",
            "Security: chattels and their location, a vehicle (logbook) or land (title deed)",
            "The price follows the loan type and fee table until the loan goes for approval",
        ],
        button: "Send to officer",
    },
    {
        key: "pending_information", state: "pending_information", icon: "fa-folder-open", tone: "teal",
        title: "Collect the documents", who: "Loan Officer",
        say: "Odoo refuses to move on while anything is missing, and says exactly what is outstanding.",
        points: [
            "Client: ID and passport photo, or registration and director's ID; 6 months of statements",
            "Loan: logbook, NTSA report and valuation; title deed and valuation; or the chattels agreement",
            "Generated agreement, signed agreement and the house visit",
            "On a first loan, the upfront fee reference",
        ],
        button: "Send for approval",
    },
    {
        key: "pending_approval", state: "pending_approval", icon: "fa-gavel", tone: "amber",
        title: "Three approvals", who: "Credit Manager, then Credit Manager, then CEO",
        say: "Three people sign off, one after the other. Each sees the loan in their Approvals list and on the dashboard.",
        points: [
            "Nobody decides an application they created, or acts on it twice",
            "A rejection needs a reason; a rejected loan can be reopened",
            "The Super Admin may decide any stage",
        ],
        button: "Approve / Reject",
    },
    {
        key: "approved", state: "approved", icon: "fa-money", tone: "green", title: "Pay out",
        who: "Finance, Head Office (never the loan's creator)",
        say: "Finance pays the client by M-Pesa, bank or cash, with its reference. Fees come off the payout.",
        points: [
            "The repayment schedule starts the next day: one instalment a day",
            "Each instalment is the daily amount; the last one is the remainder",
            "The agreement can be emailed as a PDF or sent by WhatsApp",
        ],
        button: "Disburse",
    },
    {
        key: "active", state: "active", icon: "fa-refresh", tone: "orange", title: "Collect every day",
        who: "Finance, Collections, Loan Officer",
        say: "Payments come in daily. Late loans go to Collections, who call, visit, send reminders and record promises to pay.",
        points: [
            "Each M-Pesa or bank reference is accepted once only",
            "A payment with no loan is matched by loan number, ID number or phone",
            "Default interest: 1% a day on each late, unpaid instalment",
            "Reminder SMS each morning, or a WhatsApp message in one click",
        ],
        button: "Record payment",
    },
    {
        key: "repaid", state: "repaid", icon: "fa-check-circle", tone: "purple", title: "Repaid",
        who: "Automatic",
        say: "When the last instalment is paid the loan closes by itself. The client is ready for the next loan.",
        points: [
            "Early settlement: interest for the days used (at least 14), plus any default interest; future instalments dropped",
            "The full history stays on the loan and in the audit log",
        ],
        button: "Settle early",
    },
];

/** Side roads off the journey. */
const BRANCHES = [
    {
        key: "rejected", state: "rejected", from: "pending_approval", icon: "fa-times-circle", tone: "red",
        title: "Rejected", text: "With a reason. Can be reopened and sent again.",
    },
    {
        key: "written_off", state: "written_off", from: "active", icon: "fa-ban", tone: "slate",
        title: "Written off", text: "Super Admin or CEO, with a reason. Closes the loan.",
    },
];

const ROLES = [
    { name: "Loan Officer", icon: "fa-handshake-o", tone: "cyan",
      does: ["Onboards clients", "Captures applications", "Collects documents", "Records payments", "Follows up late loans"] },
    { name: "Credit Manager", icon: "fa-search", tone: "amber",
      does: ["Approves stages 1 and 2", "Captures applications", "Can blacklist a client", "Records payments"] },
    { name: "CEO", icon: "fa-star", tone: "purple",
      does: ["Final approval (stage 3)", "Reverses payments", "Writes off loans", "Reads the audit log"] },
    { name: "Finance / Cashier", icon: "fa-money", tone: "green",
      does: ["Disburses approved loans", "Records and matches payments", "Reverses payments"] },
    { name: "Collections Officer", icon: "fa-phone", tone: "orange",
      does: ["Works the late loans list", "Sends reminders by SMS or WhatsApp", "Logs calls, visits and promises"] },
    { name: "Head Office", icon: "fa-building", tone: "indigo",
      does: ["Everything an officer does", "Disburses", "Reverses payments", "Reads the audit log"] },
    { name: "Auditor", icon: "fa-eye", tone: "slate",
      does: ["Sees everything, changes nothing", "Reads the audit log"] },
    { name: "Super Admin", icon: "fa-key", tone: "red",
      does: ["Every action", "Loan types, fees and settings", "Users and roles"] },
];

const SAFEGUARDS = [
    { icon: "fa-user-secret", title: "Personal details masked",
      text: "ID number, phones, email, KRA PIN and bank account show as ••••. To see them, staff type their own password again; they show for 60 seconds." },
    { icon: "fa-lock", title: "Lock after wrong passwords",
      text: "Five wrong passwords lock the details for five minutes." },
    { icon: "fa-list-alt", title: "Audit log nobody can edit",
      text: "Every sign-in, approval, payout, payment, reversal, write-off, client change and view of personal details: who, when and from which IP address." },
    { icon: "fa-users", title: "Four eyes on every loan",
      text: "Nobody approves their own application, and the person who created a loan never pays it out." },
    { icon: "fa-clone", title: "No double payments",
      text: "An M-Pesa or bank reference is accepted once. A reversal re-applies the loan's other payments from the start." },
    { icon: "fa-clock-o", title: "Sessions that end",
      text: "Sign out after 60 idle minutes and after 10 hours; two-factor sign-in can be enforced." },
];

/** The repayment example: a 30-day loan of 10,000 at 1% a day, on day 4. */
const EXAMPLE = { principal: 10000, rate: 0.01, days: 30, today: 4, shown: 6 };

export class MfiHowItWorks extends Component {
    static template = "mfi_loan.HowItWorks";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.parts = PARTS;
        this.journey = JOURNEY;
        this.branches = BRANCHES;
        this.roles = ROLES;
        this.safeguards = SAFEGUARDS;
        this.state = useState({
            data: null,
            step: 0,
            playing: false,
            productId: false,
            amount: 10000,
            days: 30,
            first: true,
            paid: 0,
        });
        onWillStart(async () => {
            const data = await this.orm.call("mfi.dashboard", "mfi_how_it_works_data", []);
            this.state.data = data;
            if (data.products.length) {
                this.selectProduct(data.products[0].id);
            }
        });
        onWillUnmount(() => this.stop());
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------

    goTo(key) {
        document.getElementById(`o_mfi_how_${key}`)?.scrollIntoView({
            behavior: reduceMotion() ? "auto" : "smooth",
            block: "start",
        });
    }

    async openAction(xmlid, context = {}) {
        return this.action.doAction(xmlid, { additionalContext: context });
    }

    async openState(key) {
        const action = await this.orm.call("mfi.dashboard", "mfi_dashboard_action", [key, "30d", null]);
        return this.action.doAction(action);
    }

    openStep(step) {
        return step.state ? this.openState(step.state) : this.openAction(step.open);
    }

    openSample() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "mfi.loan",
            res_id: this.state.data.sample.id,
            views: [[false, "form"]],
        });
    }

    // ------------------------------------------------------------------
    // The journey
    // ------------------------------------------------------------------

    count(stateKey) {
        if (!this.state.data) {
            return 0;
        }
        if (stateKey === "client") {
            return this.state.data.clients;
        }
        return this.state.data.states.find((s) => s.key === stateKey)?.count || 0;
    }

    stepCount(step) {
        return this.count(step.state || "client");
    }

    stepNoun(step) {
        const n = this.stepCount(step);
        if (!step.state) {
            return n === 1 ? "client" : "clients";
        }
        return n === 1 ? "loan" : "loans";
    }

    get current() {
        return this.journey[this.state.step];
    }

    get progress() {
        return (this.state.step / (this.journey.length - 1)) * 100;
    }

    select(index) {
        this.stop();
        this.state.step = index;
    }

    prev() {
        this.select(Math.max(0, this.state.step - 1));
    }

    next() {
        this.select(Math.min(this.journey.length - 1, this.state.step + 1));
    }

    togglePlay() {
        if (this.state.playing) {
            return this.stop();
        }
        if (this.state.step >= this.journey.length - 1) {
            this.state.step = 0;
        }
        this.state.playing = true;
        this.timer = browser.setInterval(() => {
            if (this.state.step >= this.journey.length - 1) {
                return this.stop();
            }
            this.state.step++;
        }, PLAY_MS);
    }

    stop() {
        if (this.timer) {
            browser.clearInterval(this.timer);
            this.timer = null;
        }
        this.state.playing = false;
    }

    // ------------------------------------------------------------------
    // Pricing calculator (same rules as rules.quote and mfi.fee._applies)
    // ------------------------------------------------------------------

    get product() {
        return this.state.data?.products.find((p) => p.id === this.state.productId);
    }

    selectProduct(id) {
        this.state.productId = Number(id);
        const product = this.product;
        if (product) {
            this.state.amount = Math.min(Math.max(this.state.amount, product.min), product.max);
        }
    }

    setAmount(value) {
        const product = this.product;
        let amount = Math.round(Number(value) || 0);
        if (product) {
            amount = Math.min(Math.max(amount, product.min), product.max);
        }
        this.state.amount = amount;
    }

    setDays(days) {
        this.state.days = days;
    }

    setFirst(first) {
        this.state.first = Boolean(first);
    }

    get amountStep() {
        const product = this.product;
        return product && product.max - product.min >= 10000 ? 500 : 100;
    }

    get quote() {
        const product = this.product;
        if (!product) {
            return null;
        }
        const { amount: principal, days, first } = this.state;
        const interest = r2(principal * product.rate * days);
        const total = r2(principal + interest);
        const daily = days ? Math.ceil(total / days) : 0;
        const fees = this.state.data.fees
            .filter((f) => (!f.min || principal >= f.min) && (!f.max || principal <= f.max)
                && (!f.first_only || first) && (!f.category || f.category === product.category))
            .map((f) => ({ ...f, upfront: Boolean(first && f.upfront_first) }));
        const deducted = r2(fees.filter((f) => !f.upfront).reduce((s, f) => s + f.amount, 0));
        const upfront = r2(fees.filter((f) => f.upfront).reduce((s, f) => s + f.amount, 0));
        const payout = r2(principal - deducted);
        const lastDay = r2(total - daily * (days - 1));
        return {
            principal, interest, total, daily, lastDay, fees, deducted, upfront, payout,
            ratePct: r2(product.rate * 100),
            penaltyPct: r2(product.penalty * 100),
            // the bar: what the client receives, the fees kept, the interest earned
            bar: [
                { key: "payout", label: "Client receives", value: payout },
                { key: "fees", label: "Fees off the payout", value: deducted },
                { key: "interest", label: "Interest", value: interest },
            ].filter((b) => b.value > 0),
            barTotal: payout + deducted + interest,
        };
    }

    // ------------------------------------------------------------------
    // Repayment example: default interest first, then instalments oldest first
    // ------------------------------------------------------------------

    get example() {
        const { principal, rate, days, today, shown } = EXAMPLE;
        const total = r2(principal + principal * rate * days);
        const daily = Math.ceil(total / days);
        let left = this.state.paid;
        // instalment n is due on day n; late ones gather 1% of the instalment a day
        const rows = [];
        let penalty = 0;
        for (let n = 1; n <= shown; n++) {
            const lateDays = Math.max(0, today - n);
            penalty += r2(daily * rate * lateDays);
            rows.push({ n, due: daily, lateDays, paid: 0 });
        }
        penalty = r2(penalty);
        const toPenalty = Math.min(left, penalty);
        left = r2(left - toPenalty);
        for (const row of rows) {
            row.paid = Math.min(left, row.due);
            left = r2(left - row.paid);
            row.pct = (row.paid / row.due) * 100;
            row.status = row.paid >= row.due ? "paid" : row.lateDays ? "late" : row.n === EXAMPLE.today ? "today" : "future";
        }
        const lateLeft = rows.some((r) => r.lateDays && r.paid < r.due) || toPenalty < penalty;
        return {
            daily, penalty, toPenalty, penaltyPct: penalty ? (toPenalty / penalty) * 100 : 100,
            rows, paid: this.state.paid, spare: left,
            health: lateLeft ? "In arrears" : "Current",
            healthTone: lateLeft ? "red" : "green",
        };
    }

    pay(amount) {
        this.state.paid = r2(this.state.paid + amount);
    }

    resetPay() {
        this.state.paid = 0;
    }

    // ------------------------------------------------------------------
    // Formatting
    // ------------------------------------------------------------------

    money(value) {
        const cur = this.state.data?.currency || "";
        const n = Number(value || 0).toLocaleString(undefined, {
            minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
            maximumFractionDigits: 2,
        });
        return `${cur} ${n}`.trim();
    }

    share(value, total) {
        return total ? `${(value / total) * 100}%` : "0%";
    }
}

registry.category("actions").add("mfi_loan.how_it_works", MfiHowItWorks);
