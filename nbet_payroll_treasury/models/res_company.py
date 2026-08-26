# -*- coding: utf-8 -*-
from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    nbet_salary_payable_account_id = fields.Many2one(
        'account.account',
        string='Salary Payable Account',
        domain="[('account_type', 'in', ('liability_current', 'liability_payable')),"
               " ('deprecated', '=', False)]",
        help='Account the payroll entry credits with net pay, and that the salary '
             'payment vouchers clear. Leave empty to take it from the credit account '
             'of each payslip\'s NET rule.',
    )
