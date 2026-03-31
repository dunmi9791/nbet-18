# -*- coding: utf-8 -*-
"""
NBET GENCO Monthly Operational Data
One record per GENCO per billing cycle.  Values may be imported from Excel
or entered manually.  Raw imported values and computed values are both stored.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class NbetGencoMonthlyData(models.Model):
    _name = 'nbet.genco.monthly.data'
    _description = 'NBET GENCO Monthly Operational Data'
    _inherit = ['mail.thread']
    _order = 'billing_cycle_id desc, participant_id'

    # ── Links ──────────────────────────────────────────────────────────────────
    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='cascade', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='GENCO',
        required=True, domain=[('participant_type', '=', 'genco')],
        ondelete='restrict', tracking=True,
    )
    contract_id = fields.Many2one(
        'nbet.genco.contract', string='Active Contract',
        compute='_compute_active_contract', store=True,
        help='Auto-fetched: the active GENCO contract valid for this billing period.',
    )

    # ── Operational Values ────────────────────────────────────────────────────
    capacity_sent_out_mw = fields.Float(
        string='Capacity Sent Out (MW)', digits=(16, 4), tracking=True,
    )
    gross_energy_kwh = fields.Float(
        string='Gross Energy (kWh)', digits=(16, 2), tracking=True,
    )
    net_energy_kwh = fields.Float(
        string='Net Energy (kWh)', digits=(16, 2), tracking=True,
    )
    capacity_import_mw = fields.Float(
        string='Import Capacity (MW)', digits=(16, 4), tracking=True,
    )
    energy_import_kwh = fields.Float(
        string='Import Energy (kWh)', digits=(16, 2), tracking=True,
    )
    net_energy_import_kwh = fields.Float(
        string='Net Import Energy (kWh)', digits=(16, 2), tracking=True,
    )
    invoiced_capacity_mw = fields.Float(
        string='Invoiced Capacity (MW)', digits=(16, 4), tracking=True,
    )
    invoiced_energy_kwh = fields.Float(
        string='Invoiced Energy (kWh)', digits=(16, 2), tracking=True,
    )
    gas_fx_rate = fields.Float(
        string='Gas FX Rate (₦/$)', digits=(16, 4),
        help='Plant-specific gas-contract FX rate, if different from CBN central rate.',
    )

    # ── Import Liability ──────────────────────────────────────────────────────
    has_import_liability = fields.Boolean(
        string='Has Import Liability', compute='_compute_import_liability', store=True,
        help='True when this GENCO imports more than it supplies — treated like a DISCO.',
    )
    import_excess_mw = fields.Float(
        string='Import Excess (MW)', compute='_compute_import_liability', store=True,
        digits=(16, 4),
    )

    @api.depends('capacity_import_mw', 'capacity_sent_out_mw')
    def _compute_import_liability(self):
        for rec in self:
            excess = rec.capacity_import_mw - rec.capacity_sent_out_mw
            rec.has_import_liability = excess > 0
            rec.import_excess_mw = max(0.0, excess)

    # ── Source / Import Metadata ───────────────────────────────────────────────
    remarks = fields.Text(string='Remarks')
    imported_from_file = fields.Boolean(string='Imported from File', default=False)
    source_row_no = fields.Integer(string='Source Row No')
    source_sheet = fields.Char(string='Source Sheet')
    source_file = fields.Char(string='Source File')

    # ── Contract Lookup ────────────────────────────────────────────────────────
    @api.depends('participant_id', 'billing_cycle_id', 'billing_cycle_id.date_start')
    def _compute_active_contract(self):
        for rec in self:
            if not rec.participant_id or not rec.billing_cycle_id:
                rec.contract_id = False
                continue
            domain = [
                ('participant_id', '=', rec.participant_id.id),
                ('state', '=', 'active'),
                '|', ('start_date', '=', False),
                ('start_date', '<=', rec.billing_cycle_id.date_start),
                '|', ('end_date', '=', False),
                ('end_date', '>=', rec.billing_cycle_id.date_start),
            ]
            contract = self.env['nbet.genco.contract'].search(domain, limit=1)
            rec.contract_id = contract

    # ── Constraints ────────────────────────────────────────────────────────────
    _sql_constraints = [
        ('cycle_participant_uniq', 'unique(billing_cycle_id, participant_id)',
         'Only one operational data record per GENCO per billing cycle is allowed.'),
    ]

    @api.constrains('participant_id')
    def _check_is_genco(self):
        for rec in self:
            if rec.participant_id and rec.participant_id.participant_type != 'genco':
                raise ValidationError(
                    f'{rec.participant_id.name} is not a GENCO. '
                    'Only GENCOs may have monthly operational data records here.'
                )
