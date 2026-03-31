# -*- coding: utf-8 -*-
"""
NBET GENCO Contract / Rate Profile
Stores the contractual rate structure, MYTO parameters, and formula mode for
each generation company.  The formula_mode field controls which calculation
path the rate engine uses for this GENCO.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class NbetGencoContract(models.Model):
    _name = 'nbet.genco.contract'
    _description = 'NBET GENCO Contract / Rate Profile'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'participant_id, start_date desc'

    # ── Identity ───────────────────────────────────────────────────────────────
    contract_name = fields.Char(string='Contract Name', required=True, tracking=True)
    contract_code = fields.Char(string='Contract Code', required=True, tracking=True)
    participant_id = fields.Many2one(
        'nbet.market.participant', string='GENCO Participant', required=True,
        domain=[('participant_type', '=', 'genco')], ondelete='restrict',
        tracking=True,
    )
    plant_type = fields.Selection(
        selection=[
            ('hydro', 'Hydro'),
            ('gas', 'Gas / Thermal (PHCN legacy)'),
            ('nipp', 'NIPP (NIPP Gas Plant)'),
            ('ipp', 'IPP (Independent Power Producer)'),
            ('thermal', 'Thermal / Coal'),
            ('other', 'Other'),
        ],
        string='Plant Type', required=True, tracking=True,
    )

    # ── Validity ───────────────────────────────────────────────────────────────
    start_date = fields.Date(string='Contract Start', tracking=True)
    end_date = fields.Date(string='Contract End', tracking=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('expired', 'Expired'),
            ('archived', 'Archived'),
        ],
        default='draft', required=True, tracking=True,
    )

    # ── Currency ───────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
    )

    # ── Base Rates ─────────────────────────────────────────────────────────────
    base_capacity_tariff = fields.Float(
        string='Base Capacity Tariff (₦/MW/h)', digits=(16, 4), tracking=True,
        help='MYTO base capacity tariff in ₦ per MW per hour.',
    )
    base_energy_tariff = fields.Float(
        string='Base Energy Tariff (₦/kWh)', digits=(16, 6), tracking=True,
        help='MYTO base energy tariff in ₦ per kWh.',
    )
    has_capacity_charge = fields.Boolean(
        string='Has Capacity Charge', default=True, tracking=True,
    )
    has_energy_charge = fields.Boolean(
        string='Has Energy Charge', default=True, tracking=True,
    )

    # ── Adjustment Flags ──────────────────────────────────────────────────────
    uses_fx_adjustment = fields.Boolean(string='Apply FX Adjustment', tracking=True)
    base_fx_rate = fields.Float(
        string='Base FX Rate (₦/$)', digits=(16, 4),
        help='The FX rate embedded in the MYTO base tariff. Used as denominator for FX adjustment.',
    )
    uses_index_adjustment = fields.Boolean(string='Apply Index Adjustment', tracking=True)
    base_index_value = fields.Float(
        string='Base Index Value', digits=(16, 6),
        help='The index value embedded in the MYTO base tariff.',
    )
    uses_tlf_adjustment = fields.Boolean(string='Apply TLF Adjustment', tracking=True)
    base_tlf = fields.Float(
        string='Base TLF', digits=(16, 6), default=1.0,
        help='Transmission Loss Factor embedded in base tariff.',
    )

    # ── Formula Mode ──────────────────────────────────────────────────────────
    formula_mode = fields.Selection(
        selection=[
            ('fixed', 'Fixed — use base tariff as-is'),
            ('parametric', 'Parametric — apply FX / TLF / index ratios'),
            ('python_expression', 'Python Expression — eval custom formula'),
            ('structured_components', 'Structured Components — sum tariff lines'),
        ],
        string='Formula Mode', default='parametric', required=True, tracking=True,
        help=(
            'fixed: Returns base_capacity_tariff and base_energy_tariff unchanged.\n'
            'parametric: Multiplies base by FX, TLF, and index adjustment ratios.\n'
            'python_expression: Evaluates formula_expression on contract lines.\n'
            'structured_components: Sums all active tariff component lines.'
        ),
    )

    # ── Tariff Components ──────────────────────────────────────────────────────
    line_ids = fields.One2many(
        'nbet.genco.contract.line', 'contract_id', string='Tariff Components',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes / Legal References')

    # ── Constraints ────────────────────────────────────────────────────────────
    _sql_constraints = [
        ('contract_code_uniq', 'unique(contract_code, company_id)',
         'Contract code must be unique per company.'),
    ]

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.start_date > rec.end_date:
                raise ValidationError('Contract end date must be after start date.')

    # ── State Transitions ──────────────────────────────────────────────────────
    def action_activate(self):
        self.write({'state': 'active'})

    def action_expire(self):
        self.write({'state': 'expired'})

    def action_archive_contract(self):
        self.write({'state': 'archived'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    # ── Name get ──────────────────────────────────────────────────────────────
    def name_get(self):
        result = []
        for rec in self:
            name = f'[{rec.contract_code}] {rec.contract_name}'
            if rec.participant_id:
                name = f'{rec.participant_id.code} — {name}'
            result.append((rec.id, name))
        return result
