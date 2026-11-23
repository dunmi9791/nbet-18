/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";
import { debounce } from "@web/core/utils/timing";

/**
 * Enhances the portal "New Time Off Request" form:
 *  - shows the half-day toggle / supporting-document field only for leave
 *    types that use them;
 *  - asks the server how many days the request uses and how much balance
 *    is left, and renders it live under the dates.
 * The server stays authoritative: it re-validates everything on submit.
 */
publicWidget.registry.NbetLeaveForm = publicWidget.Widget.extend({
    selector: ".o_nbet_leave_form",
    events: {
        "change #holiday_status_id": "_onTypeChange",
        "change #request_unit_half": "_onHalfDayChange",
        "change #request_date_from": "_onDateFromChange",
        "change #request_date_to": "_schedulePreview",
        "change #request_date_from_period": "_schedulePreview",
    },

    start() {
        this.typeSelect = this.el.querySelector("#holiday_status_id");
        this.halfDayBlock = this.el.querySelector(".o_nbet_leave_half_day");
        this.halfDayInput = this.el.querySelector("#request_unit_half");
        this.periodSelect = this.el.querySelector("#request_date_from_period");
        this.dateFrom = this.el.querySelector("#request_date_from");
        this.dateTo = this.el.querySelector("#request_date_to");
        this.dateToBlock = this.el.querySelector(".o_nbet_leave_to");
        this.fromLabel = this.el.querySelector(".o_nbet_leave_from_label");
        this.attachmentBlock = this.el.querySelector(".o_nbet_leave_attachment");
        this.preview = this.el.querySelector(".o_nbet_leave_preview");
        this._previewSeq = 0;
        this._debouncedPreview = debounce(() => this._updatePreview(), 300);

        this._applyType();
        this._schedulePreview();
        return this._super(...arguments);
    },

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    _onTypeChange() {
        this._applyType();
        this._schedulePreview();
    },

    _onHalfDayChange() {
        this._applyHalfDay();
        this._schedulePreview();
    },

    _onDateFromChange() {
        // Default the end date to the start date to save a click.
        if (this.dateFrom.value && (!this.dateTo.value || this.dateTo.value < this.dateFrom.value)) {
            this.dateTo.value = this.dateFrom.value;
        }
        this._applyHalfDay();
        this._schedulePreview();
    },

    _schedulePreview() {
        this._debouncedPreview();
    },

    //--------------------------------------------------------------------------
    // Field visibility
    //--------------------------------------------------------------------------

    _selectedOption() {
        return this.typeSelect.options[this.typeSelect.selectedIndex];
    },

    _applyType() {
        const option = this._selectedOption();
        const allowsHalfDay = option && option.dataset.halfDay === "1";
        const needsDocument = option && option.dataset.supportDocument === "1";

        this.halfDayBlock.classList.toggle("d-none", !allowsHalfDay);
        if (!allowsHalfDay) {
            this.halfDayInput.checked = false;
        }
        this.attachmentBlock.classList.toggle("d-none", !needsDocument);
        this._applyHalfDay();
    },

    _isHalfDay() {
        return !this.halfDayBlock.classList.contains("d-none") && this.halfDayInput.checked;
    },

    _applyHalfDay() {
        const halfDay = this._isHalfDay();
        this.periodSelect.classList.toggle("d-none", !halfDay);
        this.dateToBlock.classList.toggle("d-none", halfDay);
        this.dateTo.required = !halfDay;
        this.fromLabel.textContent = halfDay ? "Date" : "From";
        if (halfDay) {
            this.dateTo.value = this.dateFrom.value;
        }
    },

    //--------------------------------------------------------------------------
    // Live preview
    //--------------------------------------------------------------------------

    async _updatePreview() {
        const typeId = this.typeSelect.value;
        const halfDay = this._isHalfDay();
        if (!typeId || !this.dateFrom.value || (!halfDay && !this.dateTo.value)) {
            this._renderPreview(null);
            return;
        }
        const seq = ++this._previewSeq;
        let result;
        try {
            result = await rpc("/my/leave/preview", {
                holiday_status_id: parseInt(typeId),
                date_from: this.dateFrom.value,
                date_to: halfDay ? this.dateFrom.value : this.dateTo.value,
                half_day: halfDay,
                period: this.periodSelect.value,
            });
        } catch {
            result = null;
        }
        // Ignore responses that arrive after a newer request was sent.
        if (seq === this._previewSeq) {
            this._renderPreview(result);
        }
    },

    _fmt(value) {
        return String(Math.round(value * 100) / 100);
    },

    _renderPreview(result) {
        const box = this.preview;
        box.replaceChildren();
        box.classList.remove("alert-light", "alert-warning", "alert-danger");
        if (!result || (result.days === undefined && !result.error)) {
            box.classList.add("d-none");
            return;
        }
        box.classList.remove("d-none");

        if (result.error) {
            box.classList.add("alert-danger");
            box.textContent = result.error;
            return;
        }

        const days = result.days;
        const main = document.createElement("div");
        main.className = "fw-semibold";
        main.textContent = `This request uses ${this._fmt(days)} working day${days === 1 ? "" : "s"}.`;
        box.append(main);

        if (result.requires_allocation && result.remaining !== null && result.remaining !== undefined) {
            const balance = document.createElement("div");
            balance.className = "small";
            balance.textContent =
                `Balance: ${this._fmt(result.remaining)} day(s) available → ` +
                `${this._fmt(result.remaining_after)} after this request.`;
            box.append(balance);
        }
        if (days === 0) {
            const note = document.createElement("div");
            note.className = "small";
            note.textContent = "These dates fall on non-working days or public holidays.";
            box.append(note);
        }
        if (result.exceeds) {
            box.classList.add("alert-warning");
            const warn = document.createElement("div");
            warn.className = "small fw-semibold mt-1";
            warn.textContent = "This is more than your remaining balance, so it may be refused.";
            box.append(warn);
        } else {
            box.classList.add("alert-light");
        }
    },
});

export default publicWidget.registry.NbetLeaveForm;
