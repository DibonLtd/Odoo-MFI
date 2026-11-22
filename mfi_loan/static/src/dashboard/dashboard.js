import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";

const PERIOD_KEY = "mfi_loan.dashboard.period";
const REFRESH_MS = 5 * 60 * 1000; // figures reload on their own every 5 minutes
const reduceMotion = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

// Colours shared by cards, charts and lists (keep in step with dashboard.scss)
export const COLORS = {
    indigo: "#4f46e5",
    green: "#16a34a",
    teal: "#0d9488",
    cyan: "#0891b2",
    amber: "#d97706",
    orange: "#ea580c",
    red: "#dc2626",
    purple: "#9333ea",
    slate: "#94a3b8",
};
const HEALTH_COLORS = { current: COLORS.green, arrears: COLORS.amber, overdue: COLORS.red };
const AGEING_COLORS = [COLORS.green, COLORS.cyan, COLORS.amber, COLORS.orange, COLORS.red];

/** A number that counts up to its value, and glides to the next one on refresh. */
export class MfiCountUp extends Component {
    static template = "mfi_loan.CountUp";
    static props = { value: Number, format: Function };

    setup() {
        this.state = useState({ current: reduceMotion() ? this.props.value : 0 });
        onMounted(() => this.animate(this.state.current, this.props.value));
        onWillUpdateProps((next) => {
            if (next.value !== this.props.value) {
                this.animate(this.state.current, next.value);
            }
        });
        onWillUnmount(() => browser.cancelAnimationFrame(this.frame));
    }

    animate(from, to) {
        browser.cancelAnimationFrame(this.frame);
        if (reduceMotion() || from === to) {
            this.state.current = to;
            return;
        }
        const start = performance.now();
        const step = (now) => {
            const t = Math.min((now - start) / 900, 1);
            this.state.current = from + (to - from) * (1 - Math.pow(1 - t, 3)); // ease-out
            if (t < 1) {
                this.frame = browser.requestAnimationFrame(step);
            }
        };
        this.frame = browser.requestAnimationFrame(step);
    }

    get display() {
        return this.props.format(this.state.current);
    }
}

/** A tiny line chart of a series, drawn as SVG. */
export class MfiSparkline extends Component {
    static template = "mfi_loan.Sparkline";
    static props = { values: Array, color: { type: String, optional: true } };

    get points() {
        const values = this.props.values.length ? this.props.values : [0];
        const max = Math.max(...values, 1);
        const step = values.length > 1 ? 100 / (values.length - 1) : 100;
        return values.map((v, i) => [i * step, 28 - (v / max) * 26]);
    }
    get line() {
        return this.points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    }
    get area() {
        return `${this.line} L100,30 L0,30 Z`;
    }
}

export class MfiDashboard extends Component {
    static template = "mfi_loan.Dashboard";
    static components = { MfiCountUp, MfiSparkline };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.root = useRef("root");
        this.trendCanvas = useRef("trend");
        this.healthCanvas = useRef("health");
        this.ageingCanvas = useRef("ageing");
        this.charts = [];
        let period = "30d";
        try {
            period = browser.localStorage.getItem(PERIOD_KEY) || period;
        } catch {
            // private window: keep the default
        }
        this.state = useState({ period, data: null, loading: true, error: false, updatedAt: 0, now: Date.now() });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.load();
        });
        onMounted(() => {
            this.refreshTimer = browser.setInterval(() => this.load(), REFRESH_MS);
            this.clockTimer = browser.setInterval(() => (this.state.now = Date.now()), 30000);
        });
        useEffect(
            () => {
                this.renderCharts();
                return () => this.destroyCharts();
            },
            () => [this.state.data]
        );
        onWillUnmount(() => {
            browser.clearInterval(this.refreshTimer);
            browser.clearInterval(this.clockTimer);
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("mfi.dashboard", "mfi_dashboard_data", [this.state.period]);
            this.state.error = false;
            this.state.updatedAt = Date.now();
            this.state.now = Date.now();
        } catch (error) {
            this.state.error = true;
            if (!this.state.data) {
                throw error;
            }
        } finally {
            this.state.loading = false;
        }
    }

    async setPeriod(period) {
        if (period === this.state.period) {
            return;
        }
        this.state.period = period;
        try {
            browser.localStorage.setItem(PERIOD_KEY, period);
        } catch {
            // not remembered, no harm
        }
        await this.load();
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------

    async open(key, value = null) {
        const action = await this.orm.call("mfi.dashboard", "mfi_dashboard_action", [key, this.state.period, value]);
        return this.action.doAction(action);
    }

    openRecord(model, id) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
        });
    }

    // ------------------------------------------------------------------
    // Formatting
    // ------------------------------------------------------------------

    get greeting() {
        const hour = new Date().getHours();
        const part = hour < 12 ? _t("Good morning") : hour < 17 ? _t("Good afternoon") : _t("Good evening");
        const first = (this.state.data?.user || "").split(" ")[0];
        return first ? `${part}, ${first}` : part;
    }

    get todayLabel() {
        return new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    }

    get periodLabel() {
        const period = this.state.data?.periods.find((p) => p.key === this.state.period);
        return period ? period.label.toLowerCase() : "";
    }

    get updatedLabel() {
        if (!this.state.updatedAt) {
            return "";
        }
        const minutes = Math.floor((this.state.now - this.state.updatedAt) / 60000);
        return minutes < 1 ? _t("Updated just now") : _t("Updated %s min ago", minutes);
    }

    /** "KSh 1.2M" on cards; the full figure goes in the tooltip. */
    money(value, compact = true) {
        const currency = this.state.data?.currency || { symbol: "", position: "before" };
        const number = new Intl.NumberFormat(undefined, {
            notation: compact && Math.abs(value) >= 10000 ? "compact" : "standard",
            maximumFractionDigits: compact && Math.abs(value) >= 10000 ? 1 : 0,
        }).format(value || 0);
        return currency.position === "after" ? `${number} ${currency.symbol}` : `${currency.symbol} ${number}`;
    }

    number(value) {
        return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value || 0);
    }

    percent(value) {
        return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value || 0)}%`;
    }

    formatMoney = (value) => this.money(value);
    formatNumber = (value) => this.number(value);
    formatPercent = (value) => this.percent(value);

    /** Trend chip: up is good for every period figure on this page. */
    trend(kpi) {
        if (kpi.trend === null || kpi.trend === undefined) {
            return kpi.value ? { label: _t("New"), tone: "up", icon: "fa-star" } : null;
        }
        if (Math.abs(kpi.trend) < 0.5) {
            return { label: _t("Steady"), tone: "flat", icon: "fa-minus" };
        }
        const up = kpi.trend > 0;
        return {
            label: `${Math.abs(Math.round(kpi.trend))}%`,
            tone: up ? "up" : "down",
            icon: up ? "fa-arrow-up" : "fa-arrow-down",
        };
    }

    /** Green, amber or red for a PAR figure. */
    parTone(value, warn = 5, bad = 10) {
        return value < warn ? "good" : value < bad ? "warn" : "bad";
    }

    /** Meter width for a PAR %: 20 % or more fills the bar. */
    meter(value) {
        return Math.min((value || 0) * 5, 100);
    }

    share(amount) {
        const total = this.state.data?.book.active.amount || 0;
        return total ? Math.round((amount / total) * 100) : 0;
    }

    get pipelineTotal() {
        const p = this.state.data?.pipeline || {};
        return (p.pending_information || 0) + (p.pending_approval || 0) + (p.approved || 0);
    }

    // ------------------------------------------------------------------
    // Charts (Chart.js, loaded with web.chartjs_lib)
    // ------------------------------------------------------------------

    destroyCharts() {
        for (const chart of this.charts) {
            chart.destroy();
        }
        this.charts = [];
    }

    renderCharts() {
        const data = this.state.data;
        if (!data || !window.Chart || !this.root.el) {
            return;
        }
        const style = getComputedStyle(this.root.el);
        const text = style.color;
        const grid = "rgba(127, 127, 127, 0.15)";
        const animation = reduceMotion() ? false : { duration: 900, easing: "easeOutQuart" };
        const moneyTick = (value) => this.money(value);
        const tooltipMoney = (ctx) => ` ${ctx.dataset.label || ctx.label}: ${this.money(ctx.parsed.y ?? ctx.parsed, false)}`;

        if (this.trendCanvas.el) {
            const ctx = this.trendCanvas.el.getContext("2d");
            const fill = ctx.createLinearGradient(0, 0, 0, this.trendCanvas.el.clientHeight || 280);
            fill.addColorStop(0, "rgba(22, 163, 74, 0.35)");
            fill.addColorStop(1, "rgba(22, 163, 74, 0)");
            this.charts.push(
                new window.Chart(this.trendCanvas.el, {
                    type: "line",
                    data: {
                        labels: data.series.labels,
                        datasets: [
                            {
                                label: _t("Collected"),
                                data: data.series.collected,
                                borderColor: COLORS.green,
                                backgroundColor: fill,
                                fill: true,
                                tension: 0.35,
                                borderWidth: 2.5,
                                pointRadius: 0,
                                pointHoverRadius: 5,
                            },
                            {
                                label: _t("Due"),
                                data: data.series.due,
                                borderColor: COLORS.indigo,
                                borderDash: [6, 4],
                                fill: false,
                                tension: 0.35,
                                borderWidth: 2,
                                pointRadius: 0,
                                pointHoverRadius: 5,
                            },
                            {
                                type: "bar",
                                label: _t("Disbursed"),
                                data: data.series.disbursed,
                                backgroundColor: "rgba(147, 51, 234, 0.35)",
                                hoverBackgroundColor: COLORS.purple,
                                borderRadius: 4,
                                maxBarThickness: 18,
                            },
                        ],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation,
                        interaction: { mode: "index", intersect: false },
                        plugins: {
                            legend: { position: "bottom", labels: { color: text, usePointStyle: true, boxWidth: 8 } },
                            tooltip: { callbacks: { label: tooltipMoney } },
                        },
                        scales: {
                            x: { grid: { display: false }, ticks: { color: text, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
                            y: { beginAtZero: true, grid: { color: grid }, ticks: { color: text, callback: moneyTick } },
                        },
                    },
                })
            );
        }

        if (this.healthCanvas.el) {
            const health = data.health;
            this.charts.push(
                new window.Chart(this.healthCanvas.el, {
                    type: "doughnut",
                    data: {
                        labels: health.map((h) => h.label),
                        datasets: [
                            {
                                data: health.map((h) => h.amount),
                                backgroundColor: health.map((h) => HEALTH_COLORS[h.key]),
                                borderWidth: 0,
                                hoverOffset: 10,
                            },
                        ],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: animation && { ...animation, animateRotate: true },
                        cutout: "68%",
                        plugins: {
                            legend: { display: false },
                            tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${this.money(ctx.parsed, false)}` } },
                        },
                        onHover: (event, elements) => {
                            event.native.target.style.cursor = elements.length ? "pointer" : "default";
                        },
                        onClick: (_event, elements) => {
                            if (elements.length) {
                                this.open("health", health[elements[0].index].key);
                            }
                        },
                    },
                })
            );
        }

        if (this.ageingCanvas.el) {
            const ageing = data.ageing;
            this.charts.push(
                new window.Chart(this.ageingCanvas.el, {
                    type: "bar",
                    data: {
                        labels: ageing.map((a) => a.label),
                        datasets: [
                            {
                                label: _t("Outstanding"),
                                data: ageing.map((a) => a.amount),
                                backgroundColor: AGEING_COLORS,
                                borderRadius: 6,
                                maxBarThickness: 26,
                            },
                        ],
                    },
                    options: {
                        indexAxis: "y",
                        responsive: true,
                        maintainAspectRatio: false,
                        animation,
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    label: (ctx) =>
                                        ` ${this.money(ctx.parsed.x, false)} · ${_t("%s loans", ageing[ctx.dataIndex].count)}`,
                                },
                            },
                        },
                        scales: {
                            x: { beginAtZero: true, grid: { color: grid }, ticks: { color: text, callback: moneyTick } },
                            y: { grid: { display: false }, ticks: { color: text } },
                        },
                        onHover: (event, elements) => {
                            event.native.target.style.cursor = elements.length ? "pointer" : "default";
                        },
                        onClick: (_event, elements) => {
                            if (elements.length) {
                                this.open("ageing", ageing[elements[0].index].key);
                            }
                        },
                    },
                })
            );
        }
    }
}

registry.category("actions").add("mfi_loan.dashboard", MfiDashboard);
