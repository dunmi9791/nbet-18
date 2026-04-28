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
            ('myto_hydro', 'MYTO Hydro — structured MYTO rate component table'),
        ],
        string='Formula Mode', default='parametric', required=True, tracking=True,
        help=(
            'fixed: Returns base_capacity_tariff and base_energy_tariff unchanged.\n'
            'parametric: Multiplies base by FX, TLF, and index adjustment ratios.\n'
            'python_expression: Evaluates formula_expression on contract lines.\n'
            'structured_components: Sums all active tariff component lines.\n'
            'myto_hydro: Uses MYTO Hydro rate table (Fixed O&M, Variable O&M, '
            'Capital Recovery) with FX and CPI adjustments per the Rates sheet formulas.'
        ),
    )

    # ── MYTO Hydro Rate Table (mirrors Rates sheet C33:E42) ──────────────────
    # Fixed inputs — Column D (MYTO 2016 base values)
    myto_base_fx_rate = fields.Float(
        string='Base FX Rate (₦/$)', digits=(16, 4), default=197.0,
        help='MYTO 2016 base USD/Naira exchange rate (Rates!D35).',
    )
    myto_base_cpi = fields.Float(
        string='Base US CPI Index', digits=(16, 4), default=108.47,
        help='MYTO 2016 base US CPI index value (Rates!D36).',
    )
    myto_base_fixed_om = fields.Float(
        string='Base Fixed O&M (₦/MW/Hr)', digits=(16, 6),
        help='MYTO 2016 base Fixed O&M rate (Rates!D37).',
    )
    myto_base_variable_om = fields.Float(
        string='Base Variable O&M (₦/MWh)', digits=(16, 6),
        help='MYTO 2016 base Variable O&M rate (Rates!D38).',
    )
    myto_base_capital_recovery = fields.Float(
        string='Base Capital Recovery (₦/MW/Hr)', digits=(16, 6),
        help='MYTO 2016 base Capital Recovery rate (Rates!D39).',
    )

    # Derived row expressions — user writes how D40, D41, D42 are composed
    # Variables available: base_fixed_om, base_variable_om, base_capital_recovery
    energy_charge_expr = fields.Char(
        string='Energy Charge Expression',
        default='base_variable_om',
        help=(
            'Expression evaluated to derive the base Energy Charge (Rates!D40).\n'
            'Available variables: base_fixed_om, base_variable_om, base_capital_recovery\n'
            'Default (D40 = D38): base_variable_om'
        ),
    )
    capacity_charge_expr = fields.Char(
        string='Capacity Charge Expression',
        default='base_fixed_om + base_capital_recovery',
        help=(
            'Expression evaluated to derive the base Capacity Charge (Rates!D41).\n'
            'Available variables: base_fixed_om, base_variable_om, base_capital_recovery\n'
            'Default (D41 = D37+D39): base_fixed_om + base_capital_recovery'
        ),
    )
    wholesale_charge_expr = fields.Char(
        string='Wholesale Charge Expression',
        default='energy_charge + capacity_charge',
        help=(
            'Expression evaluated to derive the base Wholesale Charge (Rates!D42).\n'
            'Available variables: base_fixed_om, base_variable_om, base_capital_recovery,\n'
            '  energy_charge, capacity_charge\n'
            'Default (D42 = D40+D41): energy_charge + capacity_charge'
        ),
    )

    # Billing input codes that supply the current-period FX and CPI (for Column E)
    myto_fx_input_code = fields.Char(
        string='Current FX Input Code',
        default='CBN_FX_CENTRAL',
        help='Billing input type code for the current-month USD/Naira rate (Rates!E35 source).',
    )
    myto_cpi_input_code = fields.Char(
        string='Current CPI Input Code',
        default='US_CPI',
        help='Billing input type code for the current-month US CPI index (Rates!E36 source).',
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
