import { registry } from "@web/core/registry";

/**
 * Page guides for the current user, loaded once per session and matched
 * locally (no server call per page).
 */
export const mfiGuideService = {
    dependencies: ["orm"],
    start(env, { orm }) {
        let guidesPromise = null;

        function load() {
            guidesPromise ||= orm.silent.call("mfi.guide", "mfi_get_guides", []).catch(() => []);
            return guidesPromise;
        }

        /** Most specific guide wins: action + view, action, model + view, model. */
        function match(guides, { resModel, viewType, actionId }) {
            const score = (guide) => {
                if (guide.model !== resModel) {
                    return -1;
                }
                if (guide.action_id && guide.action_id !== actionId) {
                    return -1;
                }
                if (guide.view_type && guide.view_type !== viewType) {
                    return -1;
                }
                return (guide.action_id ? 2 : 0) + (guide.view_type ? 1 : 0);
            };
            let best = null;
            let bestScore = -1;
            for (const guide of guides) {
                const value = score(guide);
                if (value > bestScore || (value >= 0 && value === bestScore && guide.sequence < best.sequence)) {
                    best = guide;
                    bestScore = value;
                }
            }
            return best;
        }

        return {
            load,
            match,
            async find(context) {
                return match(await load(), context);
            },
            async hide(guideId) {
                await orm.call("res.users", "mfi_hide_guide", [guideId]);
                const guides = await load();
                guidesPromise = Promise.resolve(guides.filter((guide) => guide.id !== guideId));
            },
        };
    },
};

registry.category("services").add("mfi_guide", mfiGuideService);
