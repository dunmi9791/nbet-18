# -*- coding: utf-8 -*-
"""
NBET Billing Run Log
Immutable audit trail for every calculation run on a billing cycle.
Created by the calculation service; should never be edited by users.
"""
from odoo import models, fields


class NbetBillingRunLog(models.Model):
    _name = 'nbet.billing.run.log'
    _description = 'NBET Billing Calculation Run Log'
    _order = 'run_date desc'

    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='cascade', index=True,
    )
    run_date = fields.Datetime(
        string='Run Date', default=fields.Datetime.now, readonly=True,
    )
    run_by = fields.Many2one(
        'res.users', string='Run By',
        default=lambda self: self.env.user, readonly=True,
    )
    run_type = fields.Selection(
        selection=[
            ('rate_compute', 'Rate Computation'),
            ('genco_bill_compute', 'GENCO Bill Computation'),
            ('disco_bill_compute', 'DISCO Bill Computation'),
            ('full_compute', 'Full Cycle Computation'),
            ('recompute', 'Recomputation'),
            ('reset', 'Cycle Reset'),
            ('accounting_post', 'Accounting Document Creation'),
        ],
        string='Run Type', required=True,
    )
    status = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('partial', 'Partial Success'),
            ('failed', 'Failed'),
        ],
        string='Status', required=True,
    )
    notes = fields.Text(string='Summary Notes')
    error_log = fields.Text(string='Error Details')
    genco_records_affected = fields.Integer(string='GENCO Records Processed')
    disco_records_affected = fields.Integer(string='DISCO Records Processed')
    duration_seconds = fields.Float(string='Duration (seconds)', digits=(10, 3))
