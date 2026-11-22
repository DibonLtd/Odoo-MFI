import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

import { Component, markup, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";

/** Green "What to do here" box under the control panel of any Microfinance page. */
export class MfiGuideBanner extends Component {
    static template = "mfi_loan.GuideBanner";
    static props = {};

    setup() {
        this.guideService = useService("mfi_guide");
        this.action = useService("action");
        this.state = useState({ guide: null });
        onWillStart(() => this.refresh());
        onWillUpdateProps(() => this.refresh());
    }

    get context() {
        return {
            resModel: this.env.searchModel?.resModel,
            viewType: this.env.config?.viewType,
            actionId: this.env.config?.actionId,
        };
    }

    get bodyMarkup() {
        return markup(this.state.guide?.body || "");
    }

    async refresh() {
        const context = this.context;
        // Not in pop-ups (e.g. "Search more..." lists): guides are for full pages.
        const show = context.resModel && !this.env.inDialog;
        this.state.guide = show ? await this.guideService.find(context) : null;
    }

    onButton(button) {
        return this.action.doAction(button.action_id);
    }

    async onClose() {
        const guide = this.state.guide;
        this.state.guide = null;
        await this.guideService.hide(guide.id);
    }
}

// Exposed through the prototype rather than ControlPanel.components: subclasses
// copy `{ ...ControlPanel.components }` into their own map when their module
// loads, possibly before this one, and would then miss the component. Prototype
// lookup is live, so every subclass sees it.
patch(ControlPanel.prototype, {
    get MfiGuideBanner() {
        return MfiGuideBanner;
    },
});
