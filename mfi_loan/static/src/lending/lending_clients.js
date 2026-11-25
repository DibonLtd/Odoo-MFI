import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

import { STATE_LABELS, STATE_TONES, formatWhen } from "./lending_utils";

/** The lending service's clients, read live and paged by its cursor (D-007). */
export class MfiLendingClients extends Component {
    static template = "mfi_loan.LendingClients";
    props = useProps({ ...standardActionServiceProps });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.states = Object.entries(STATE_LABELS);
        this.tones = STATE_TONES;
        this.state = proxy({ loading: true, filter: "", items: [], cursors: [null], page: 0, next: null,
                             fetchedAt: null, error: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const cursor = this.state.cursors[this.state.page];
        const result = await this.orm.call("res.partner", "mfi_lending_list", [], {
            state: this.state.filter || null,
            cursor,
        });
        if (result.ok) {
            this.state.items = result.page.items || [];
            this.state.next = result.page.nextCursor || null;
            this.state.fetchedAt = formatWhen(result.page.fetchedAt);
            this.state.error = null;
        } else {
            this.state.error = result.error;
            if (result.error.code === "invalid_cursor") {
                this.state.cursors = [null];
                this.state.page = 0;
            }
        }
        this.state.loading = false;
    }

    setFilter(value) {
        this.state.filter = value;
        this.state.cursors = [null];
        this.state.page = 0;
        return this.load();
    }

    nextPage() {
        if (!this.state.next) {
            return;
        }
        this.state.cursors[this.state.page + 1] = this.state.next;
        this.state.page += 1;
        return this.load();
    }

    previousPage() {
        if (this.state.page) {
            this.state.page -= 1;
            return this.load();
        }
    }

    stateLabel(value) {
        return STATE_LABELS[value] || value;
    }

    created(item) {
        return formatWhen(item.createdAt);
    }

    open(item) {
        if (!item.odoo) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "mfi_loan.lending_onboarding",
            name: item.odoo.clientNo,
            params: { partner_id: item.odoo.id },
        });
    }
}

registry.category("actions").add("mfi_loan.lending_clients", MfiLendingClients);
