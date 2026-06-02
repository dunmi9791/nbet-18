/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class ProcurementDashboard extends Component {
    static template = "nbet_procurement.ProcurementDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            assessments: { draft: 0, submitted: 0, approved: 0, total: 0 },
            plans: { draft: 0, ppc_review: 0, approved: 0, implementing: 0, total: 0 },
            bids: { draft: 0, advertised: 0, tec_evaluation: 0, approved: 0, total: 0 },
            contracts: { draft: 0, in_execution: 0, completed: 0, total: 0 },
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        const [assessments, plans, bids, contracts] = await Promise.all([
            this.orm.searchRead("nbet.needs.assessment", [], ["state"]),
            this.orm.searchRead("nbet.procurement.plan", [], ["state"]),
            this.orm.searchRead("nbet.bid.evaluation", [], ["state"]),
            this.orm.searchRead("nbet.contract.award", [], ["state"]),
        ]);

        this.state.assessments = this._countStates(assessments, ["draft", "submitted", "approved"]);
        this.state.plans = this._countStates(plans, ["draft", "ppc_review", "approved", "implementing"]);
        this.state.bids = this._countStates(bids, ["draft", "advertised", "tec_evaluation", "approved"]);
        this.state.contracts = this._countStates(contracts, ["draft", "in_execution", "completed"]);
    }

    _countStates(records, stateKeys) {
        const counts = { total: records.length };
        for (const key of stateKeys) {
            counts[key] = records.filter((r) => r.state === key).length;
        }
        return counts;
    }

    openAction(actionXmlId, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: this._getModel(actionXmlId),
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openFiltered(model, name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: model,
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    _getModel(key) {
        const models = {
            assessments: "nbet.needs.assessment",
            plans: "nbet.procurement.plan",
            bids: "nbet.bid.evaluation",
            contracts: "nbet.contract.award",
        };
        return models[key];
    }
}

registry.category("actions").add("nbet_procurement_dashboard", ProcurementDashboard);
