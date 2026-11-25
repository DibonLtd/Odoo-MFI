import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

import { Component, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";

import {
    CHECK_LABELS,
    DOCUMENT_STATES,
    FIELD_LABELS,
    OUTCOME_LABELS,
    OUTCOME_TONES,
    STATE_LABELS,
    STATE_TONES,
    checklistLabel,
    documentLabel,
    formatWhen,
    readAsBase64,
} from "./lending_utils";

const POLL_MS = 5000; // while checks run
const ACCEPTED_FILES = "image/jpeg,image/png,application/pdf";

/**
 * One client's onboarding in the lending service. Everything shown is read live
 * and never stored (DECISIONS D-007); a command is offered only when the
 * service lists it in `actions` (D-008).
 */
export class MfiLendingOnboarding extends Component {
    static template = "mfi_loan.LendingOnboarding";
    props = useProps({ ...standardActionServiceProps });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.partnerId = this.props.action.params?.partner_id || this.props.action.context?.active_id;
        this.acceptedFiles = ACCEPTED_FILES;
        this.labels = { STATE_LABELS, STATE_TONES, DOCUMENT_STATES, CHECK_LABELS, OUTCOME_LABELS, OUTCOME_TONES };
        this.state = proxy({
            loading: true,
            busy: false,
            partner: null,
            client: null,
            documents: null,
            verifications: null,
            error: null,
            code: "",
            codeSent: null,
            now: Date.now(),
            contact: { phone: "", email: "", county: "", town: "", street: "", landmark: "" },
            editing: false,
            uploadType: "",
            linkTypes: [],
            linkChannel: "SMS",
        });
        onWillStart(() => this.load());
        this.clock = browser.setInterval(() => (this.state.now = Date.now()), 1000);
        onWillUnmount(() => {
            browser.clearInterval(this.clock);
            browser.clearTimeout(this.pollTimer);
        });
    }

    // ------------------------------------------------------------------
    // Reading
    // ------------------------------------------------------------------

    async load() {
        this.state.loading = true;
        const result = await this.orm.call("res.partner", "mfi_lending_read", [[this.partnerId]]);
        this.state.partner = result.partner;
        if (result.ok) {
            this.state.client = result.client;
            this.state.documents = result.documents;
            this.state.verifications = result.verifications || null;
            this.state.error = null;
            this.state.uploadType = this.uploadTypes[0] || "";
        } else {
            this.state.error = result.error;
        }
        this.state.loading = false;
        this.schedulePoll();
    }

    schedulePoll() {
        browser.clearTimeout(this.pollTimer);
        if (this.state.client?.state === "VERIFYING") {
            this.pollTimer = browser.setTimeout(() => this.poll(), POLL_MS);
        }
    }

    async poll() {
        const result = await this.orm.call("res.partner", "mfi_lending_command", [[this.partnerId], "verifications"]);
        if (result.ok) {
            this.state.verifications = result.verifications;
            if (result.verifications.state !== "VERIFYING") {
                return this.load();
            }
        }
        this.schedulePoll();
    }

    get client() {
        return this.state.client;
    }

    can(action) {
        return Boolean(this.state.partner?.canAct && this.client?.actions?.includes(action));
    }

    get partnerName() {
        return this.state.partner ? this.state.partner.name : "";
    }

    get partnerNo() {
        return (this.state.partner && this.state.partner.clientNo) || "";
    }

    get sentTo() {
        return (this.state.codeSent && this.state.codeSent.sentTo) || this.client.phone;
    }

    get codeInvalid() {
        return Boolean(this.state.error && this.state.error.field === "code");
    }

    get held() {
        return this.client?.state === "HELD";
    }

    get fetchedAt() {
        return formatWhen(this.client?.fetchedAt);
    }

    get fullName() {
        const c = this.client || {};
        return [c.firstName, c.middleName, c.lastName].filter(Boolean).join(" ");
    }

    get checklist() {
        return (this.client?.checklist || []).map((item) => ({ ...item, label: checklistLabel(item.item) }));
    }

    get missingDocumentTypes() {
        return (this.client?.checklist || [])
            .filter((item) => item.item.startsWith("document:") && !item.done)
            .map((item) => item.item.slice("document:".length));
    }

    get uploadTypes() {
        const required = (this.client?.checklist || [])
            .filter((item) => item.item.startsWith("document:"))
            .map((item) => item.item.slice("document:".length));
        return required.length ? required : ["ID_DOCUMENT", "CLIENT_PHOTO"];
    }

    get documents() {
        return (this.state.documents?.items || []).map((doc) => ({
            ...doc,
            label: documentLabel(doc.documentType),
            stateLabel: DOCUMENT_STATES[doc.state] || doc.state,
            updated: formatWhen(doc.updatedAt),
        }));
    }

    get checks() {
        return (this.state.verifications?.checks || []).map((check) => ({
            ...check,
            label: CHECK_LABELS[check.check] || check.check,
            outcomeLabel: OUTCOME_LABELS[check.outcome] || check.outcome,
            tone: OUTCOME_TONES[check.outcome] || "secondary",
            fieldLabel: check.field ? FIELD_LABELS[check.field] || check.field : "",
            at: formatWhen(check.at),
        }));
    }

    get resendIn() {
        const after = this.state.codeSent?.resendAfter;
        if (!after) {
            return 0;
        }
        return Math.max(0, Math.ceil((Date.parse(after) - this.state.now) / 1000));
    }

    documentLabel(type) {
        return documentLabel(type);
    }

    // ------------------------------------------------------------------
    // Commands
    // ------------------------------------------------------------------

    async command(name, params = {}, success = "") {
        if (this.state.busy) {
            return null;
        }
        this.state.busy = true;
        this.state.error = null;
        try {
            const result = await this.orm.call("res.partner", "mfi_lending_command", [[this.partnerId], name, params]);
            if (!result.ok) {
                this.state.error = result.error;
                if (result.client) {
                    this.state.client = result.client; // stale: show the fresh version
                }
                return null;
            }
            if (success) {
                this.notification.add(success, { type: "success" });
            }
            return result;
        } finally {
            this.state.busy = false;
        }
    }

    async sendCode() {
        const result = await this.command("send_phone_code", {}, _t("Code sent."));
        if (result) {
            this.state.codeSent = result.sent;
            await this.load();
        } else if (this.state.error?.retryAfterSeconds) {
            this.state.codeSent = {
                resendAfter: new Date(Date.now() + this.state.error.retryAfterSeconds * 1000).toISOString(),
            };
        }
    }

    async confirmCode() {
        const code = (this.state.code || "").trim();
        if (!/^[0-9]{6}$/.test(code)) {
            this.state.error = { kind: "local", message: _t("The code has 6 digits."), field: "code" };
            return;
        }
        if (await this.command("confirm_phone", { code }, _t("Phone confirmed."))) {
            this.state.code = "";
            this.state.codeSent = null;
            await this.load();
        }
    }

    startEditing() {
        this.state.contact = { phone: "", email: "", county: "", town: "", street: "", landmark: "" };
        this.state.editing = true;
    }

    async saveContact() {
        const c = this.state.contact;
        const values = {};
        if (c.phone.trim()) {
            values.phone = c.phone.trim();
        }
        if (c.email.trim()) {
            values.email = c.email.trim();
        }
        if (["county", "town", "street", "landmark"].some((k) => c[k].trim())) {
            values.address = Object.fromEntries(
                ["county", "town", "street", "landmark"].map((k) => [k, c[k].trim() || null])
            );
        }
        if (!Object.keys(values).length) {
            this.state.editing = false;
            return;
        }
        if (await this.command("update_contact", { values }, _t("Contact details saved."))) {
            this.state.editing = false;
            await this.load();
        }
    }

    async upload(ev) {
        const file = ev.target.files?.[0];
        ev.target.value = "";
        if (!file || !this.state.uploadType) {
            return;
        }
        if (!this.acceptedFiles.split(",").includes(file.type)) {
            this.state.error = { kind: "local", message: _t("Only JPEG, PNG or PDF files are accepted.") };
            return;
        }
        const data = await readAsBase64(file);
        const params = { documentType: this.state.uploadType, contentType: file.type, data };
        if (await this.command("upload_file", params, _t("File sent. The lending service checks it now."))) {
            await this.load();
        }
    }

    toggleLinkType(type) {
        const types = this.state.linkTypes;
        const index = types.indexOf(type);
        if (index >= 0) {
            types.splice(index, 1);
        } else {
            types.push(type);
        }
    }

    async sendLink() {
        const documentTypes = this.state.linkTypes.length ? [...this.state.linkTypes] : this.missingDocumentTypes;
        if (!documentTypes.length) {
            return;
        }
        const result = await this.command(
            "send_upload_link",
            { documentTypes, channel: this.state.linkChannel },
            _t("Upload link sent.")
        );
        if (result) {
            this.state.linkTypes = [];
        }
    }

    async submit() {
        if (await this.command("submit", {}, _t("Submitted: the checks are running."))) {
            await this.load();
        }
    }

    openClient() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: this.partnerId,
            views: [[false, "form"]],
            context: { form_view_ref: "mfi_loan.mfi_client_view_form" },
        });
    }
}

registry.category("actions").add("mfi_loan.lending_onboarding", MfiLendingOnboarding);
