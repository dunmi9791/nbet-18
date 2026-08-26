# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nbet_salary_payable_account_id = fields.Many2one(
        related='company_id.nbet_salary_payable_account_id',
        string='Salary Payable Account',
        readonly=False,
    )
