/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

/**
 * Counts the installed/available/generated capacity figures up from zero the
 * first time the block scrolls into view, mirroring the odometer effect on
 * www.nbet.com.ng.
 *
 * Markup contract (see views/snippets/s_nbet_capacity.xml):
 *   <span class="s_nbet_counter_value" data-target-value="13014" data-duration="2000"/>
 */
const NbetCounterWidget = publicWidget.Widget.extend({
    selector: ".s_nbet_capacity",
    // Numbers should sit still while the site builder is open, otherwise the
    // editor saves whatever intermediate value the animation was on.
    disabledInEditableMode: true,

    /**
     * @override
     */
    start() {
        this.counterEls = [...this.el.querySelectorAll(".s_nbet_counter_value")];
        this.animations = [];

        // Show the final figure immediately when the visitor has asked for
        // reduced motion, or when IntersectionObserver is unavailable.
        const prefersReducedMotion = window.matchMedia(
            "(prefers-reduced-motion: reduce)"
        ).matches;
        if (prefersReducedMotion || !window.IntersectionObserver) {
            this.counterEls.forEach((el) => this._render(el, this._targetOf(el)));
            return this._super(...arguments);
        }

        this.counterEls.forEach((el) => this._render(el, 0));

        this.observer = new window.IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        this._animate(entry.target);
                        this.observer.unobserve(entry.target);
                    }
                }
            },
            { threshold: 0.35 }
        );
        this.counterEls.forEach((el) => this.observer.observe(el));

        return this._super(...arguments);
    },

    /**
     * @override
     */
    destroy() {
        if (this.observer) {
            this.observer.disconnect();
        }
        this.animations.forEach((id) => window.cancelAnimationFrame(id));
        // Leave the final figure on screen so the block still reads correctly
        // once the widget is torn down (e.g. when entering edit mode).
        (this.counterEls || []).forEach((el) =>
            this._render(el, this._targetOf(el))
        );
        this._super(...arguments);
    },

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * @private
     * @param {HTMLElement} el
     * @returns {number}
     */
    _targetOf(el) {
        const target = parseFloat(el.dataset.targetValue);
        return Number.isFinite(target) ? target : 0;
    },

    /**
     * Writes the value out using the visitor's locale grouping so 13014 reads
     * as "13,014".
     *
     * @private
     * @param {HTMLElement} el
     * @param {number} value
     */
    _render(el, value) {
        const decimals = parseInt(el.dataset.decimals) || 0;
        el.textContent = value.toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
    },

    /**
     * @private
     * @param {HTMLElement} el
     */
    _animate(el) {
        const target = this._targetOf(el);
        const duration = parseInt(el.dataset.duration) || 2000;
        const start = performance.now();

        const step = (now) => {
            const progress = Math.min((now - start) / duration, 1);
            // easeOutCubic — fast start, gentle settle onto the final figure.
            const eased = 1 - Math.pow(1 - progress, 3);
            this._render(el, target * eased);

            if (progress < 1) {
                this.animations.push(window.requestAnimationFrame(step));
            } else {
                this._render(el, target);
            }
        };

        this.animations.push(window.requestAnimationFrame(step));
    },
});

publicWidget.registry.NbetCounter = NbetCounterWidget;

export default NbetCounterWidget;
