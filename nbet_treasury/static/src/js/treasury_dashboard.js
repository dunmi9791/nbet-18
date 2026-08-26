/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

// Approval stages a payment moves through before it is paid.
const UNPAID_STATES = [
    "pending", "scheduled", "cfo_approved", "fm_approved",
    "voucher_generated", "audit_pending", "audit_reviewed",
];
const PIPELINE_STATES = [...UNPAID_STATES, "audited"];

class TreasuryDashboard extends Component {
    static template = "nbet_treasury.TreasuryDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            counts: {
                pending: 0,
                scheduled: 0,
                cfo_approved: 0,
                fm_approved: 0,
                audited: 0,
                paid: 0,
                on_hold: 0,
                total: 0,
                overdue: 0,
            },
            totals: {
                pending_amount: 0,
                audited_amount: 0,
                paid_amount: 0,
                pipeline_amount: 0,
            },
            recent_paid: [],
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        const records = await this.orm.searchRead(
            "nbet.payment.schedule",
            [],
            ["state", "amount", "scheduled_date", "name", "vendor_id", "description", "payment_date"],
        );

        const today = new Date().toISOString().split("T")[0];

        const counts = {
            pending: 0, scheduled: 0, cfo_approved: 0, fm_approved: 0,
            voucher_generated: 0, audit_pending: 0, audit_reviewed: 0,
            audited: 0, paid: 0, on_hold: 0, total: records.length, overdue: 0,
        };
        const totals = {
            pending_amount: 0, audited_amount: 0, paid_amount: 0, pipeline_amount: 0,
        };

        for (const rec of records) {
            if (counts[rec.state] !== undefined) {
                counts[rec.state]++;
            }
            if (rec.state === "pending") {
                totals.pending_amount += rec.amount;
            }
            if (PIPELINE_STATES.includes(rec.state)) {
                totals.pipeline_amount += rec.amount;
            }
            if (rec.state === "audited") {
                totals.audited_amount += rec.amount;
            }
            if (rec.state === "paid") {
                totals.paid_amount += rec.amount;
            }
            if (
                UNPAID_STATES.includes(rec.state) &&
                rec.scheduled_date && rec.scheduled_date < today
            ) {
                counts.overdue++;
            }
        }

        const paidRecords = records
            .filter((r) => r.state === "paid")
            .sort((a, b) => (b.payment_date || "").localeCompare(a.payment_date || ""))
            .slice(0, 5);

        this.state.counts = counts;
        this.state.totals = totals;
        this.state.recent_paid = paidRecords;
    }

    formatCurrency(value) {
        return new Intl.NumberFormat("en-NG", {
            style: "currency",
            currency: "NGN",
            minimumFractionDigits: 2,
        }).format(value);
    }

    openAll() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "All Payment Schedules",
            res_model: "nbet.payment.schedule",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openFiltered(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: "nbet.payment.schedule",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }
}

registry.category("actions").add("nbet_treasury_dashboard", TreasuryDashboard);
