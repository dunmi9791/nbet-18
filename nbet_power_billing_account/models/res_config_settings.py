# -*- coding: utf-8 -*-
"""
NBET Power Billing - Accounting Configuration via res.config.settings
Extends Odoo's standard settings to expose nbet.billing.config fields.
"""
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Revenue Accounts ──────────────────────────────────────────────────────
    nbet_revenue_capacity_account_id = fields.Many2one(
        'account.account',
        string='Capacity Revenue Account',
        config_parameter='nbet_power_billing.revenue_capacity_account_id',
        domain=[('account_type', 'in', ['income', 'income_other'])],
        help='Credit account for DISCO capacity revenue lines.',
    )
    nbet_revenue_energy_account_id = fields.Many2one(
        'account.account',
        string='Energy Revenue Account',
        config_parameter='nbet_power_billing.revenue_energy_account_id',
        domain=[('account_type', 'in', ['income', 'income_other'])],
        help='Credit account for DISCO energy revenue lines.',
    )

    # ── Expense Accounts ──────────────────────────────────────────────────────
    nbet_expense_capacity_account_id = fields.Many2one(
        'account.account',
        string='Capacity Expense Account',
        config_parameter='nbet_power_billing.expense_capacity_account_id',
        domain=[('account_type', 'in', ['expense', 'expense_depreciation', 'expense_direct_cost'])],
        help='Debit account for GENCO capacity charge expense lines.',
    )
    nbet_expense_energy_account_id = fields.Many2one(
        'account.account',
        string='Energy Expense Account',
        config_parameter='nbet_power_billing.expense_energy_account_id',
        domain=[('account_type', 'in', ['expense', 'expense_depreciation', 'expense_direct_cost'])],
        help='Debit account for GENCO energy charge expense lines.',
    )

    # ── Subsidy / Grant Accounts ───────────────────────────────────────────────
    nbet_subsidy_receivable_account_id = fields.Many2one(
        'account.account',
        string='Subsidy Receivable Account',
        config_parameter='nbet_power_billing.subsidy_receivable_account_id',
        domain=[('account_type', '=', 'asset_receivable')],
        help='Receivable account for government subsidy amounts.',
    )
    nbet_grant_receivable_account_id = fields.Many2one(
        'account.account',
        string='Grant Receivable Account',
        config_parameter='nbet_power_billing.grant_receivable_account_id',
        domain=[('account_type', '=', 'asset_receivable')],
        help='Receivable account for grant funding amounts.',
    )
    nbet_import_charge_account_id = fields.Many2one(
        'account.account',
        string='Import Charge Account',
        config_parameter='nbet_power_billing.import_charge_account_id',
        help='Account for GENCO import liability charges.',
    )
    nbet_adjustment_account_id = fields.Many2one(
        'account.account',
        string='Adjustment Account',
        config_parameter='nbet_power_billing.adjustment_account_id',
        help='Account for billing adjustments and prior-period corrections.',
    )

    # ── Journals ──────────────────────────────────────────────────────────────
    nbet_payable_journal_id = fields.Many2one(
        'account.journal',
        string='GENCO Payable Journal',
        config_parameter='nbet_power_billing.payable_journal_id',
        domain=[('type', 'in', ['purchase', 'general'])],
        help='Journal for GENCO vendor bills.',
    )
    nbet_receivable_journal_id = fields.Many2one(
        'account.journal',
        string='DISCO Receivable Journal',
        config_parameter='nbet_power_billing.receivable_journal_id',
        domain=[('type', 'in', ['sale', 'general'])],
        help='Journal for DISCO customer invoices.',
    )
    nbet_subsidy_journal_id = fields.Many2one(
        'account.journal',
        string='Subsidy/Grant Journal',
        config_parameter='nbet_power_billing.subsidy_journal_id',
        domain=[('type', '=', 'general')],
        help='Journal for subsidy and grant journal entries.',
    )

    # ── Workflow Settings ─────────────────────────────────────────────────────
    nbet_disco_invoice_mode = fields.Selection(
        [
            ('dro_only', 'DRO Portion Only (subsidy tracked off-ledger)'),
            ('full_with_credit', 'Full Amount + Subsidy Credit Note'),
            ('dro_plus_subsidy_receivable', 'DRO Invoice + Separate Subsidy Receivable'),
        ],
        string='DISCO Invoice Mode',
        config_parameter='nbet_power_billing.disco_invoice_mode',
        default='dro_only',
        help=(
            'dro_only: Invoice DISCO only for their DRO-payable portion. '
            'Subsidy tracked in operational reports only.\n'
            'full_with_credit: Invoice DISCO for the full gross amount, then '
            'post a subsidy credit note for the shortfall.\n'
            'dro_plus_subsidy_receivable: Invoice DISCO for DRO portion and '
            'create a separate receivable entry against the subsidy partner.'
        ),
    )
    nbet_auto_post_invoices = fields.Boolean(
        string='Auto-Post Invoices',
        config_parameter='nbet_power_billing.auto_post_invoices',
        default=False,
        help='If enabled, invoices and vendor bills are posted automatically after creation. '
             'Leave disabled to review drafts before posting.',
    )
    nbet_variance_tolerance_percent = fields.Float(
        string='Variance Tolerance (%)',
        config_parameter='nbet_power_billing.variance_tolerance_percent',
        default=1.0,
        help='Maximum acceptable variance % between GENCO submitted invoice and expected bill '
             'before the submission is flagged for review.',
    )
    nbet_create_analytic_tags = fields.Boolean(
        string='Create Analytic Dimensions',
        config_parameter='nbet_power_billing.create_analytic_tags',
        default=False,
        help='Automatically attach analytic account/dimensions to accounting lines.',
    )

    # ── Subsidy Partner ───────────────────────────────────────────────────────
    nbet_subsidy_partner_id = fields.Many2one(
        'res.partner',
        string='Subsidy Sponsor (Partner)',
        config_parameter='nbet_power_billing.subsidy_partner_id',
        help='The government entity or agency that provides subsidy funding. '
             'Used as the partner in subsidy receivable journal entries (mode 3).',
    )

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers to read settings as a dict (used by accounting_service)
    # ──────────────────────────────────────────────────────────────────────────

    @api.model
    def get_nbet_accounting_config(self):
        """Return a dict of resolved NBET accounting configuration values.
        Resolves ICP keys to actual record objects where applicable."""
        ICP = self.env['ir.config_parameter'].sudo()

        def _get_account(key):
            val = ICP.get_param(f'nbet_power_billing.{key}')
            if val:
                return self.env['account.account'].browse(int(val)).exists()
            return self.env['account.account']

        def _get_journal(key):
            val = ICP.get_param(f'nbet_power_billing.{key}')
            if val:
                return self.env['account.journal'].browse(int(val)).exists()
            return self.env['account.journal']

        def _get_partner(key):
            val = ICP.get_param(f'nbet_power_billing.{key}')
            if val:
                return self.env['res.partner'].browse(int(val)).exists()
            return self.env['res.partner']

        return {
            'revenue_capacity_account': _get_account('revenue_capacity_account_id'),
            'revenue_energy_account': _get_account('revenue_energy_account_id'),
            'expense_capacity_account': _get_account('expense_capacity_account_id'),
            'expense_energy_account': _get_account('expense_energy_account_id'),
            'subsidy_receivable_account': _get_account('subsidy_receivable_account_id'),
            'grant_receivable_account': _get_account('grant_receivable_account_id'),
            'import_charge_account': _get_account('import_charge_account_id'),
            'adjustment_account': _get_account('adjustment_account_id'),
            'payable_journal': _get_journal('payable_journal_id'),
            'receivable_journal': _get_journal('receivable_journal_id'),
            'subsidy_journal': _get_journal('subsidy_journal_id'),
            'disco_invoice_mode': ICP.get_param('nbet_power_billing.disco_invoice_mode', 'dro_only'),
            'auto_post_invoices': ICP.get_param('nbet_power_billing.auto_post_invoices', 'False') == 'True',
            'variance_tolerance_percent': float(ICP.get_param('nbet_power_billing.variance_tolerance_percent', '1.0')),
            'create_analytic_tags': ICP.get_param('nbet_power_billing.create_analytic_tags', 'False') == 'True',
            'subsidy_partner': _get_partner('subsidy_partner_id'),
        }
