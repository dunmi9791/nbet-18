# -*- coding: utf-8 -*-
"""
NBET Billing Configuration (per company)
Stores accounting configuration for the billing module as a proper model.
The res.config.settings extension in nbet_power_billing_account writes to ICP;
this model is a convenient single-record store per company.
"""
from odoo import models, fields, api
from odoo.exceptions import UserError


class NbetBillingConfig(models.Model):
    _name = 'nbet.billing.config'
    _description = 'NBET Billing Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, ondelete='cascade',
    )

    # ── Revenue Accounts ──────────────────────────────────────────────────────
    revenue_capacity_account_id = fields.Many2one('account.account', string='Capacity Revenue Account')
    revenue_energy_account_id = fields.Many2one('account.account', string='Energy Revenue Account')

    # ── Expense Accounts ──────────────────────────────────────────────────────
    expense_capacity_account_id = fields.Many2one('account.account', string='Capacity Expense Account')
    expense_energy_account_id = fields.Many2one('account.account', string='Energy Expense Account')

    # ── Subsidy / Grant Accounts ───────────────────────────────────────────────
    subsidy_receivable_account_id = fields.Many2one('account.account', string='Subsidy Receivable Account')
    grant_receivable_account_id = fields.Many2one('account.account', string='Grant Receivable Account')
    import_charge_account_id = fields.Many2one('account.account', string='Import Charge Account')
    adjustment_account_id = fields.Many2one('account.account', string='Adjustment Account')

    # ── Journals ──────────────────────────────────────────────────────────────
    payable_journal_id = fields.Many2one('account.journal', string='GENCO Payable Journal',
                                          domain=[('type', 'in', ['purchase', 'general'])])
    receivable_journal_id = fields.Many2one('account.journal', string='DISCO Receivable Journal',
                                             domain=[('type', 'in', ['sale', 'general'])])
    subsidy_journal_id = fields.Many2one('account.journal', string='Subsidy/Grant Journal',
                                          domain=[('type', '=', 'general')])

    # ── Workflow ──────────────────────────────────────────────────────────────
    disco_invoice_mode = fields.Selection(
        selection=[
            ('dro_only', 'DRO Portion Only'),
            ('full_with_credit', 'Full Amount + Subsidy Credit Note'),
            ('dro_plus_subsidy_receivable', 'DRO Invoice + Separate Subsidy Receivable'),
        ],
        default='dro_only', required=True,
    )
    auto_post_invoices = fields.Boolean(default=False)
    variance_tolerance_percent = fields.Float(default=1.0, digits=(5, 2))
    create_analytic_tags = fields.Boolean(default=False)
    subsidy_partner_id = fields.Many2one('res.partner', string='Subsidy Sponsor')

    _sql_constraints = [
        ('company_uniq', 'unique(company_id)', 'Only one billing configuration per company.'),
    ]

    @api.model
    def get_config(self, company=None):
        """Return or create the billing config for the given company."""
        if company is None:
            company = self.env.company
        config = self.search([('company_id', '=', company.id)], limit=1)
        if not config:
            config = self.create({'company_id': company.id})
        return config
