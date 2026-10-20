/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

const BAR_COLORS = [
    "#8b5cf6", "#f59e0b", "#0891b2", "#16a34a",
    "#ef4444", "#ec4899", "#3b82f6", "#f97316",
];

export class WarrantyDashboard extends Component {
    static template = "warranty_mgmt.WarrantyDashboard";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            loading: true,
            data: null,
        });

        onWillStart(async () => {
            await this._loadAll();
        });
    }

    async _loadAll() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "warranty.dashboard", "get_warranty_dashboard_data", []
            );
        } catch (err) {
            console.error("Warranty Dashboard load error:", err);
        }
        this.state.loading = false;
    }

    async onRefresh() {
        await this._loadAll();
    }

    // ----------------------------------------------------------------
    // Navigation
    // ----------------------------------------------------------------
    openRecord(model, resId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            views: [[false, "form"]],
            res_id: resId,
            target: "current",
        });
    }

    _openList(name, model, domain) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain: domain || [],
            target: "current",
        });
    }

    _todayStr() {
        return new Date().toISOString().split("T")[0];
    }

    _soonStr() {
        const d = new Date();
        d.setDate(d.getDate() + 30);
        return d.toISOString().split("T")[0];
    }

    // ----------------------------------------------------------------
    // Card -> filtered list actions
    // ----------------------------------------------------------------
    viewActive() {
        this._openList("Active Warranties", "warranty.coverage", [["state", "=", "active"]]);
    }

    viewExpiring() {
        this._openList("Expiring Soon", "warranty.coverage", [
            ["state", "=", "active"],
            ["expiry_date", ">=", this._todayStr()],
            ["expiry_date", "<=", this._soonStr()],
        ]);
    }

    viewExpired() {
        this._openList("Expired Warranties", "warranty.coverage", [["state", "=", "expired"]]);
    }

    viewByOrigin(origin, label) {
        this._openList(label, "warranty.coverage", [["warranty_origin", "=", origin]]);
    }

    viewAllCoverages() {
        this._openList("All Warranties", "warranty.coverage", []);
    }

    viewOpenClaims() {
        this._openList("Open Claims", "warranty.claim", [["state", "in", ["submitted", "approved"]]]);
    }

    viewAllClaims() {
        this._openList("All Claims", "warranty.claim", []);
    }

    viewCoveragesByState(stateKey) {
        this._openList("Warranties", "warranty.coverage", [["state", "=", stateKey]]);
    }

    viewClaimsByState(stateKey) {
        this._openList("Claims", "warranty.claim", [["state", "=", stateKey]]);
    }

    // ----------------------------------------------------------------
    // Chart / badge helpers
    // ----------------------------------------------------------------
    barHeight(list, count) {
        const max = Math.max(...list.map((i) => i.count), 1);
        return Math.round((count / max) * 90);
    }

    barColor(index) {
        return BAR_COLORS[index % BAR_COLORS.length];
    }

    coverageBadge(stateKey) {
        const map = {
            draft: "wd-badge-grey",
            active: "wd-badge-green",
            expired: "wd-badge-red",
            claimed: "wd-badge-orange",
            void: "wd-badge-grey",
            cancelled: "wd-badge-grey",
        };
        return "wd-badge " + (map[stateKey] || "wd-badge-blue");
    }

    claimBadge(stateKey) {
        const map = {
            draft: "wd-badge-grey",
            submitted: "wd-badge-orange",
            approved: "wd-badge-blue",
            rejected: "wd-badge-red",
            resolved: "wd-badge-green",
        };
        return "wd-badge " + (map[stateKey] || "wd-badge-blue");
    }

    daysBadge(daysLeft) {
        if (daysLeft <= 7) return "wd-badge wd-badge-red";
        if (daysLeft <= 15) return "wd-badge wd-badge-orange";
        return "wd-badge wd-badge-green";
    }
}

registry.category("actions").add("warranty_dashboard", WarrantyDashboard);
