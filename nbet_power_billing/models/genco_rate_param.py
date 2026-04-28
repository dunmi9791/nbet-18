# -*- coding: utf-8 -*-
"""
NBET GENCO Contract MYTO Rate Parameter
Stores the named base index parameters for the MYTO component formula mode.
Each row represents one parameter from the Rates sheet Column D header block
(e.g. USD/Naira FX, US CPI, Nigerian CPI, Gas Fuel Price).

The code is used as a variable name in component formula expressions:
  base_<code>    → this row's base_value (MYTO baseline, Column D)
  current_<code> → value pulled from billing_input_code for the period (Column E)

Example for Hydros:
  code='fx',   base_value=197,    billing_input_code='CBN_FX_CENTRAL'
  code='cpi',  base_value=108.47, billing_input_code='US_CPI'

Component formula can then reference: base_value * (current_fx / base_fx) * (current_cpi / base_cpi)
"""
from odoo import models, fields


class NbetGencoRateParam(models.Model):
    _name = 'nbet.genco.rate.param'
    _description = 'GENCO Contract MYTO Rate Parameter'
    _order = 'contract_id, sequence, id'

    contract_id = fields.Many2one(
        'nbet.genco.contract', string='Contract',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Seq.', default=10)

    # ── Parameter Identity ────────────────────────────────────────────────────
    code = fields.Char(
        string='Code', required=True,
        help=(
            'Short machine-readable identifier, no spaces (e.g. fx, cpi, ncpi, gas).\n'
            'Used in component formulas as base_<code> and current_<code>.\n'
            'Example: code="fx" → base_fx = 197, current_fx = 1328.04'
        ),
    )
    name = fields.Char(
        string='Description', required=True,
        help='Human-readable label, e.g. "USD/Naira FX Rate (₦/$)".',
    )

    # ── Values ────────────────────────────────────────────────────────────────
    base_value = fields.Float(
        string='Base Value (MYTO)',
        digits=(16, 6),
        help='The MYTO baseline value embedded in the base tariff (Column D in Rates sheet).',
    )
    billing_input_code = fields.Char(
        string='Billing Input Code',
        help=(
            'Code of the nbet.billing.input.type that supplies the current-period '
            'value for this parameter (Column E source in Rates sheet).\n'
            'Example: CBN_FX_CENTRAL, US_CPI, NG_CPI, GAS_PRICE_MMBTU'
        ),
    )
