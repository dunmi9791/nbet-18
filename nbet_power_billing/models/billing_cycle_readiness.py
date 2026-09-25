# -*- coding: utf-8 -*-
"""
NBET Billing Cycle Input Readiness
One line per gap found when checking a billing cycle against the contracts of
the GENCOs that participated in it (those with monthly operational data).
Lines are rebuilt by nbet.billing.cycle.action_check_inputs(); blocking lines
stop rate calculation and review until the missing inputs are entered.
"""
from odoo import models, fields


class NbetBillingCycleReadiness(models.Model):
    _name = 'nbet.billing.cycle.readiness'
    _description = 'NBET Billing Cycle Input Readiness Issue'
    _order = 'billing_cycle_id, severity, input_code, participant_id'

    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='cascade', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='GENCO', ondelete='cascade',
    )
    contract_id = fields.Many2one(
        'nbet.genco.contract', string='Contract', ondelete='set null',
    )
    severity = fields.Selection(
        selection=[
            ('blocking', 'Blocking'),
            ('warning', 'Warning'),
        ],
        string='Severity', required=True,
    )
    issue_type = fields.Selection(
        selection=[
            ('no_contract', 'No Active Contract'),
            ('missing_input', 'Missing Input'),
            ('zero_input', 'Input Is Zero'),
            ('setup_gap', 'Contract Set-up Gap'),
            ('missing_monthly_data', 'Monthly Quantity Is Zero'),
        ],
        string='Issue', required=True,
    )
    input_code = fields.Char(string='Input Code')
    input_type_id = fields.Many2one(
        'nbet.billing.input.type', string='Input Type', ondelete='set null',
    )
    description = fields.Char(string='Details')
