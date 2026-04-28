# -*- coding: utf-8 -*-
"""
NBET GENCO Contract Tariff Component Line
Each line represents one component of the GENCO's tariff structure.
The rate engine uses these lines when formula_mode = 'structured_components'.
They can also serve as documentation for 'parametric' and 'python_expression' modes.
"""
from odoo import models, fields, api


class NbetGencoContractLine(models.Model):
    _name = 'nbet.genco.contract.line'
    _description = 'NBET GENCO Contract Tariff Component'
    _order = 'contract_id, sequence, id'

    contract_id = fields.Many2one(
        'nbet.genco.contract', string='Contract',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)

    # ── Component Identity ────────────────────────────────────────────────────
    component_type_id = fields.Many2one(
        'nbet.genco.component.type',
        string='Component Type', required=True,
    )
    component_type = fields.Char(related='component_type_id.code', string='Type Code', store=True)
    name = fields.Char(string='Component Name', required=True)
    component_code = fields.Char(
        string='Component Code',
        help=(
            'Short machine-readable identifier for this component (no spaces).\n'
            'Once computed, the result is available under this name in subsequent '
            'component formulas within the same contract.\n'
            'Examples: fixed_om, variable_om, vfcr, capital_recovery, energy_charge, '
            'capacity_charge, wholesale_charge.'
        ),
    )

    # ── Value Basis ───────────────────────────────────────────────────────────
    basis = fields.Selection(
        selection=[
            ('fixed_value', 'Fixed Value'),
            ('formula', 'Formula Expression'),
            ('input_reference', 'Billing Input Reference'),
            ('rate_reference', 'Rate Reference'),
        ],
        string='Basis', required=True, default='fixed_value',
    )
    base_value = fields.Float(
        string='Base Value (MYTO)',
        digits=(16, 6),
        help=(
            'The MYTO baseline rate for this component (Column D in Rates sheet).\n'
            'Available as the variable base_value inside the Formula Expression.'
        ),
    )
    formula_expression = fields.Text(
        string='Monthly Rate Formula',
        help=(
            'Python expression that computes this component\'s current-period rate.\n\n'
            'For MYTO Components mode the context includes:\n'
            '  base_value          — this line\'s Base Value (MYTO baseline)\n'
            '  base_<code>         — base value of each contract rate parameter\n'
            '  current_<code>      — current-period value of each rate parameter\n'
            '  <component_code>    — already-computed value of earlier component lines\n\n'
            'Examples (Hydros):\n'
            '  Fixed O&M:       base_value * (current_fx / base_fx) * (current_cpi / base_cpi)\n'
            '  Capital Recovery: base_value * (current_fx / base_fx)\n'
            '  Energy Charge:   variable_om\n'
            '  Capacity Charge: fixed_om + capital_recovery\n\n'
            'For structured_components / python_expression modes the context includes:\n'
            '  base_capacity, base_energy, fx_rate, base_fx, tlf, base_tlf,\n'
            '  index, base_index, hours, capacity_sent_out, net_energy.'
        ),
    )
    input_type_code = fields.Char(
        string='Input Type Code',
        help='Code of the nbet.billing.input.type to pull value from.',
    )
    value = fields.Float(
        string='Fixed Value', digits=(16, 6),
        help='Used when basis = fixed_value.',
    )
    uom_description = fields.Char(
        string='Unit / Description',
        help='e.g. ₦/MW/h, ₦/kWh, %, ratio',
    )

    # ── Computed result field (populated at runtime by calculation service) ───
    computed_value = fields.Float(
        string='Last Computed Value', digits=(16, 6),
        help='Populated by the calculation service during billing run.',
    )
    computed_trace = fields.Text(
        string='Last Computed Trace',
        help='Human-readable trace of how computed_value was derived.',
    )
