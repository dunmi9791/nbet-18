# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nbet_niso_partner_id = fields.Many2one(
        'res.partner',
        string='NISO Partner',
        config_parameter='nbet_niso.partner_id',
        help='The Nigerian Independent System Operator record. Defaulted onto new '
             'advices and used as the debtor on the receivable.',
    )
    nbet_niso_income_account_id = fields.Many2one(
        'account.account',
        string='Admin Charge Income Account',
        config_parameter='nbet_niso.income_account_id',
        domain=[('account_type', 'in', ['income', 'income_other']), ('deprecated', '=', False)],
        help='Revenue account credited when an advice is confirmed.',
    )
    nbet_niso_sale_journal_id = fields.Many2one(
        'account.journal',
        string='Admin Charge Sales Journal',
        config_parameter='nbet_niso.sale_journal_id',
        domain=[('type', '=', 'sale')],
        help='Journal the receivable invoice is raised in. Falls back to the first '
             'sales journal of the company when left empty.',
    )
