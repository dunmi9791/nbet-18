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
    component_type = fields.Selection(
        selection=[
            ('capacity', 'Capacity Charge'),
            ('energy', 'Energy Charge'),
            ('fx', 'FX Adjustment'),
            ('gas', 'Gas / Fuel Component'),
            ('index', 'Index Adjustment'),
            ('tlf', 'TLF (Transmission Loss Factor)'),
            ('adjustment', 'Adjustment / Penalty'),
            ('import_charge', 'Import Liability Charge'),
            ('other', 'Other'),
        ],
        string='Component Type', required=True,
    )
    name = fields.Char(string='Component Name', required=True)

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
    formula_expression = fields.Text(
        string='Formula Expression',
        help=(
            'Python expression evaluated in the rate engine context.\n'
            'Available variables: base_capacity, base_energy, fx_rate, base_fx,\n'
            'tlf, base_tlf, index, base_index, hours, capacity_sent_out, net_energy.'
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
