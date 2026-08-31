# -*- coding: utf-8 -*-
"""
NBET DISCO → GENCO Rate Allocation
Per-cycle input lines declaring what percentage of a DISCO's bill is billed
against a specific GENCO's rates.  Any unallocated remainder is billed at the
weighted average of GENCO rates for the cycle.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class NbetDiscoGencoAllocation(models.Model):
    _name = 'nbet.disco.genco.allocation'
    _description = 'NBET DISCO GENCO Rate Allocation'
    _order = 'disco_data_id, genco_id'

    disco_data_id = fields.Many2one(
        'nbet.disco.monthly.data', string='DISCO Monthly Data',
        required=True, ondelete='cascade', index=True,
    )
    billing_cycle_id = fields.Many2one(
        related='disco_data_id.billing_cycle_id', store=True,
    )
    disco_id = fields.Many2one(
        related='disco_data_id.participant_id', string='DISCO', store=True,
    )
    genco_id = fields.Many2one(
        'nbet.market.participant', string='GENCO',
        required=True, domain=[('participant_type', '=', 'genco')],
        ondelete='restrict',
    )
    allocation_percent = fields.Float(
        string='Allocation (%)', digits=(5, 2), required=True,
        help='Percentage of the DISCO\'s delivered quantities billed at this '
             'GENCO\'s rates. The unallocated remainder is billed at the '
             'weighted average of GENCO rates.',
    )
    currency_id = fields.Many2one(
        'res.currency', related='billing_cycle_id.currency_id',
    )

    _sql_constraints = [
        ('disco_data_genco_uniq', 'unique(disco_data_id, genco_id)',
         'Only one allocation line per GENCO per DISCO data record is allowed.'),
    ]

    @api.constrains('allocation_percent')
    def _check_percent_range(self):
        for rec in self:
            if rec.allocation_percent <= 0 or rec.allocation_percent > 100:
                raise ValidationError(
                    'Allocation percentage must be greater than 0 and at most 100.'
                )

    @api.constrains('allocation_percent', 'disco_data_id')
    def _check_total_percent(self):
        for data in self.mapped('disco_data_id'):
            total = sum(data.allocation_line_ids.mapped('allocation_percent'))
            if total > 100.0 + 1e-6:
                raise ValidationError(
                    f'GENCO allocations for {data.participant_id.name} total '
                    f'{total:.2f}%. The total must not exceed 100%.'
                )

    @api.constrains('genco_id')
    def _check_is_genco(self):
        for rec in self:
            if rec.genco_id and rec.genco_id.participant_type != 'genco':
                raise ValidationError(
                    f'{rec.genco_id.name} is not a GENCO.'
                )
