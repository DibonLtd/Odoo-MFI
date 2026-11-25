import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

import { Component, onMounted, onWillUnmount, proxy, useProps } from "@odoo/owl";

/**
 * Bulk push: one call per selected client, in the person's own session, so each
 * is made as them (DECISIONS D-011). Safe to run again: done steps are skipped.
 */
export class MfiLendingPush extends Component {
    static template = "mfi_loan.LendingPush";
    props = useProps({ ...standardActionServiceProps });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const ids = this.props.action.params?.ids || [];
        this.state = proxy({
            rows: ids.map((id) => ({ id, name: "", status: "waiting", message: "" })),
            running: false,
            stopped: false,
        });
        onMounted(() => this.run());
        onWillUnmount(() => (this.state.stopped = true));
    }

    get done() {
        return this.state.rows.filter((r) => r.status !== "waiting" && r.status !== "sending").length;
    }

    get succeeded() {
        return this.state.rows.filter((r) => r.status === "ok").length;
    }

    get progress() {
        return this.state.rows.length ? Math.round((this.done / this.state.rows.length) * 100) : 100;
    }

    async run() {
        this.state.running = true;
        for (const row of this.state.rows) {
            if (this.state.stopped) {
                break;
            }
            if (row.status === "ok") {
                continue;
            }
            row.status = "sending";
            try {
                const result = await this.orm.call("res.partner", "mfi_lending_push", [[row.id]]);
                row.name = result.name || row.name;
                row.clientNo = result.clientNo;
                row.status = result.ok ? "ok" : "refused";
                row.message = result.ok ? "" : result.error.message;
            } catch (error) {
                row.status = "refused";
                row.message = error.data?.message || error.message || String(error);
            }
        }
        this.state.running = false;
    }

    async close() {
        this.state.stopped = true;
        await this.action.doAction({ type: "ir.actions.act_window_close" });
        await this.action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
    }
}

registry.category("actions").add("mfi_loan.lending_push", MfiLendingPush);
