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
        """Return or create the billing config for the given company.

        Settings > NBET Power Billing (nbet_power_billing_account) stores its
        values as ir.config_parameter keys. Any field left empty here is
        filled from those keys so invoicing works whichever screen was used.
        """
        if company is None:
            company = self.env.company
        Config = self.sudo()
        config = Config.search([('company_id', '=', company.id)], limit=1)
        if not config:
            config = Config.create({'company_id': company.id})
        config._fill_from_settings()
        return self.browse(config.id)

    def _fill_from_settings(self):
        """Copy values saved through Settings into empty fields of this record."""
        ICP = self.env['ir.config_parameter'].sudo()
        for rec in self:
            vals = {}
            for fname, field in rec._fields.items():
                if field.type != 'many2one' or fname == 'company_id' or rec[fname]:
                    continue
                param = ICP.get_param(f'nbet_power_billing.{fname}')
                if not param or not param.isdigit():
                    continue
                target = self.env[field.comodel_name].sudo().browse(int(param)).exists()
                if target:
                    vals[fname] = target.id
            if vals:
                rec.sudo().write(vals)

    @api.model
    def action_open_config(self):
        """Open the current company's configuration instead of a blank form."""
        config = self.get_config()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'nbet_power_billing.action_nbet_billing_config')
        action['res_id'] = config.id
        return action
