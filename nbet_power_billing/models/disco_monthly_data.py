# -*- coding: utf-8 -*-
"""
NBET DISCO Monthly Operational Data
One record per DISCO per billing cycle capturing delivered energy/capacity
and the DRO applied at billing time.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class NbetDiscoMonthlyData(models.Model):
    _name = 'nbet.disco.monthly.data'
    _description = 'NBET DISCO Monthly Operational Data'
    _inherit = ['mail.thread']
    _order = 'billing_cycle_id desc, participant_id'

    # ── Links ──────────────────────────────────────────────────────────────────
    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='cascade', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='DISCO',
        required=True, domain=[('participant_type', '=', 'disco')],
        ondelete='restrict', tracking=True,
    )

    # ── Delivered Quantities ───────────────────────────────────────────────────
    capacity_delivered_mw = fields.Float(
        string='Capacity Delivered (MW)', digits=(16, 4), tracking=True,
    )
    energy_delivered_kwh = fields.Float(
        string='Energy Delivered (kWh)', digits=(16, 2), tracking=True,
    )
    market_allocation_basis = fields.Char(
        string='Allocation Basis',
        help='Description of how this DISCO\'s share was allocated (e.g. ATC-based, metered).',
    )

    # ── Applied DRO (frozen at billing time) ──────────────────────────────────
    applied_dro_id = fields.Many2one(
        'nbet.disco.dro', string='Applied DRO Record', tracking=True,
        help='The DRO history record whose rate was applied. Frozen after billing.',
    )
    applied_dro_percent = fields.Float(
        string='Applied DRO (%)', digits=(5, 2), tracking=True,
        help='DRO % frozen at billing time. Will not change even if master DRO is updated.',
    )

    # ── Computed Exposures ────────────────────────────────────────────────────
    expected_payable_amount = fields.Float(
        string='Expected Payable', digits=(16, 2), tracking=True,
    )
    subsidy_amount = fields.Float(
        string='Subsidy Amount', digits=(16, 2), tracking=True,
    )
    grant_amount = fields.Float(
        string='Grant Amount', digits=(16, 2), tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='billing_cycle_id.currency_id',
    )
    remarks = fields.Text(string='Remarks')

    # ── Constraints ────────────────────────────────────────────────────────────
    _sql_constraints = [
        ('cycle_participant_uniq', 'unique(billing_cycle_id, participant_id)',
         'Only one data record per DISCO per billing cycle is allowed.'),
    ]

    @api.constrains('participant_id')
    def _check_is_disco(self):
        for rec in self:
            if rec.participant_id and rec.participant_id.participant_type != 'disco':
                raise ValidationError(
                    f'{rec.participant_id.name} is not a DISCO. '
                    'Only DISCOs may have monthly operational data records here.'
                )

    # ── DRO Lookup Helper ──────────────────────────────────────────────────────
    def _fetch_applicable_dro(self):
        """Find and apply the correct DRO record effective for this billing cycle.
        Stores the result in applied_dro_id and applied_dro_percent.
        Returns the DRO record or raises if none found."""
        self.ensure_one()
        if not self.billing_cycle_id or not self.participant_id:
            return self.env['nbet.disco.dro']
        dro = self.env['nbet.disco.dro'].get_dro_for_date(
            self.participant_id.id,
            self.billing_cycle_id.date_start,
        )
        if dro:
            self.applied_dro_id = dro.id
            self.applied_dro_percent = dro.dro_percent
        return dro
