# -*- coding: utf-8 -*-
"""
NBET Billing Cycle Input
Stores each auditable input value for a billing cycle with full traceability
back to the source document, sheet, and cell (for Excel-imported values).
"""
from odoo import models, fields, api


class NbetBillingCycleInput(models.Model):
    _name = 'nbet.billing.cycle.input'
    _description = 'NBET Billing Cycle Input Value'
    _order = 'billing_cycle_id, input_type_id'

    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='cascade', index=True,
    )
    input_type_id = fields.Many2one(
        'nbet.billing.input.type', string='Input Type', required=True,
        ondelete='restrict',
    )

    # ── Value Fields (one used depending on input_type.value_type) ────────────
    value_float = fields.Float(string='Float Value', digits=(16, 6))
    value_char = fields.Char(string='Text Value')
    value_date = fields.Date(string='Date Value')
    value_monetary = fields.Float(string='Monetary Value', digits=(16, 2))
    currency_id = fields.Many2one(
        'res.currency', related='billing_cycle_id.currency_id',
    )

    # ── Source Traceability ────────────────────────────────────────────────────
    source_document = fields.Char(string='Source Document',
                                   help='e.g. "CBN Market Rates April 2024"')
    source_sheet = fields.Char(string='Source Sheet',
                                help='Excel sheet name where value was found.')
    source_cell = fields.Char(string='Source Cell',
                               help='Cell reference, e.g. B14')
    remarks = fields.Text(string='Remarks')

    # ── Computed Display ──────────────────────────────────────────────────────
    computed_display_value = fields.Char(
        compute='_compute_display_value', string='Value',
    )

    @api.depends(
        'input_type_id', 'input_type_id.value_type',
        'value_float', 'value_char', 'value_date', 'value_monetary',
    )
    def _compute_display_value(self):
        for rec in self:
            vtype = rec.input_type_id.value_type if rec.input_type_id else 'float'
            if vtype == 'float':
                rec.computed_display_value = f'{rec.value_float:,.6f}'
            elif vtype == 'monetary':
                rec.computed_display_value = f'{rec.value_monetary:,.2f}'
            elif vtype == 'percent':
                rec.computed_display_value = f'{rec.value_float:.4f}%'
            elif vtype == 'integer':
                rec.computed_display_value = str(int(rec.value_float))
            elif vtype == 'text':
                rec.computed_display_value = rec.value_char or ''
            elif vtype == 'date':
                rec.computed_display_value = str(rec.value_date) if rec.value_date else ''
            else:
                rec.computed_display_value = str(rec.value_float)

    def get_float_value(self):
        """Convenience method: return the effective float value based on value_type."""
        self.ensure_one()
        vtype = self.input_type_id.value_type if self.input_type_id else 'float'
        if vtype == 'monetary':
            return self.value_monetary
        elif vtype == 'text':
            try:
                return float(self.value_char or 0)
            except (ValueError, TypeError):
                return 0.0
        else:
            return self.value_float
