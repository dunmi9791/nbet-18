# -*- coding: utf-8 -*-
"""
NBET GENCO Contract / Rate Profile
Stores the contractual rate structure, MYTO parameters, and formula mode for
each generation company.  The formula_mode field controls which calculation
path the rate engine uses for this GENCO.
"""
import ast

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from odoo.tools.safe_eval import _BUILTINS

# Formula variables the parametric / python_expression paths read from fixed
# billing input codes (see nbet.calculation.service._build_eval_context).
EXPRESSION_INPUT_CODES = {
    'fx_rate': 'CBN_FX_CENTRAL',
    'tlf': 'TLF_NEW',
    'index': 'AGIP_INDEX',
}
EXPRESSION_CONTEXT_NAMES = {
    'base_capacity', 'base_energy', 'fx_rate', 'base_fx', 'tlf', 'base_tlf',
    'index', 'base_index', 'hours', 'capacity_sent_out', 'net_energy',
    'invoiced_capacity', 'invoiced_energy',
}


def formula_names(expression):
    """Return the free variable names a formula reads (builtins excluded).

    Raises SyntaxError when the expression cannot be parsed.
    """
    tree = ast.parse(expression.strip(), mode='eval')
    bound = set()
    loaded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (loaded if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    return loaded - bound - set(_BUILTINS)


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
            ('myto_components', 'MYTO Components — base param table + component formulas'),
        ],
        string='Formula Mode', default='parametric', required=True, tracking=True,
        help=(
            'fixed: Returns base_capacity_tariff and base_energy_tariff unchanged.\n'
            'parametric: Multiplies base by FX, TLF, and index adjustment ratios.\n'
            'python_expression: Evaluates formula_expression on contract lines.\n'
            'structured_components: Sums all active tariff component lines.\n'
            'myto_components: Evaluates each component line\'s formula against the '
            'contract\'s named base parameter table. Works for any plant type — '
            'configure the params and component lines to match the Rates sheet.'
        ),
    )

    # ── MYTO Base Parameter Table ─────────────────────────────────────────────
    # Stores the named index parameters (FX, CPI, gas price, etc.) per contract.
    # Each param holds the MYTO base value (Column D) and the billing input code
    # that supplies the current-period value (Column E source).
    rate_param_ids = fields.One2many(
        'nbet.genco.rate.param', 'contract_id',
        string='MYTO Base Parameters',
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

    # ── Input Requirements ─────────────────────────────────────────────────────
    def _get_input_requirements(self):
        """Work out what this contract's rate formulas need from a billing cycle.

        Mirrors the lookups nbet.calculation.service performs for each
        formula_mode, so the billing cycle can flag gaps before calculating.

        Returns:
            tuple(dict, list):
              inputs       — {input_code: [reason, ...]} billing inputs read
              setup_issues — [message, ...] contract set-up problems that make
                             the engine silently fall back (bad formula, flag
                             enabled with a zero base value, ...)
        """
        self.ensure_one()
        inputs = {}
        issues = []

        def need(code, reason):
            inputs.setdefault(code, []).append(reason)

        def names_of(line):
            try:
                return formula_names(line.formula_expression)
            except SyntaxError as e:
                issues.append(f'{line.name}: formula has a syntax error ({e.msg}).')
                return None

        lines = self.line_ids.filtered('active')
        mode = self.formula_mode

        if mode == 'parametric':
            for flag, base_field, code, label in (
                ('uses_fx_adjustment', 'base_fx_rate', 'CBN_FX_CENTRAL', 'FX adjustment'),
                ('uses_tlf_adjustment', 'base_tlf', 'TLF_NEW', 'TLF adjustment'),
                ('uses_index_adjustment', 'base_index_value', 'AGIP_INDEX', 'Index adjustment'),
            ):
                if not self[flag]:
                    continue
                if not self[base_field]:
                    issues.append(
                        f'{label} is enabled but {self._fields[base_field].string} '
                        'is 0, so the adjustment is skipped.'
                    )
                else:
                    need(code, label)

        elif mode == 'python_expression':
            for line in lines.filtered(
                lambda l: l.basis == 'formula' and l.formula_expression
                and l.component_type in ('capacity', 'energy')
            ):
                names = names_of(line)
                if names is None:
                    continue
                for name in sorted(names - EXPRESSION_CONTEXT_NAMES):
                    issues.append(f'{line.name}: formula uses unknown name "{name}".')
                for var, code in EXPRESSION_INPUT_CODES.items():
                    if var in names:
                        need(code, f'{line.name} formula ({var})')

        elif mode == 'structured_components':
            for line in lines.filtered(lambda l: l.component_type in ('capacity', 'energy')):
                if line.basis == 'input_reference':
                    if line.input_type_code:
                        need(line.input_type_code, line.name)
                    else:
                        issues.append(
                            f'{line.name}: basis is Billing Input Reference '
                            'but no Input Type Code is set.'
                        )
                elif line.basis == 'formula' and line.formula_expression:
                    # Structured formulas are evaluated directly against the
                    # billing input dict, so every name is an input code.
                    for name in sorted(names_of(line) or ()):
                        need(name, f'{line.name} formula')

        elif mode == 'myto_components':
            params = self.rate_param_ids.filtered('code')
            known = {'base_value'}
            for p in params:
                known |= {f'base_{p.code}', f'current_{p.code}'}
            used = set()
            for line in lines.filtered(lambda l: l.basis == 'formula' and l.formula_expression):
                names = names_of(line)
                if names is not None:
                    used |= names
                    for name in sorted(names - known):
                        issues.append(
                            f'{line.name}: formula uses "{name}", which is not a rate '
                            'parameter or an earlier component code.'
                        )
                if line.component_code:
                    known.add(line.component_code)
            # A param without an input code is a deliberate constant (base value).
            for p in params:
                if p.billing_input_code and f'current_{p.code}' in used:
                    need(p.billing_input_code, f'rate parameter "{p.code}" ({p.name})')

        return inputs, issues

    # ── Name get ──────────────────────────────────────────────────────────────
    def name_get(self):
        result = []
        for rec in self:
            name = f'[{rec.contract_code}] {rec.contract_name}'
            if rec.participant_id:
                name = f'{rec.participant_id.code} — {name}'
            result.append((rec.id, name))
        return result
