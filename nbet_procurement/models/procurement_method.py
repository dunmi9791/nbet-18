# -*- coding: utf-8 -*-
from odoo import models, fields


class ProcurementMethod(models.Model):
    _name = 'nbet.procurement.method'
    _description = 'Procurement Method'
    _order = 'min_amount'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    category = fields.Selection([
        ('goods', 'Goods'),
        ('works', 'Works'),
        ('non_consultant', 'Non-Consultant Services'),
        ('consultant', 'Consultant Services'),
    ], required=True)
    min_amount = fields.Float(string='Minimum Amount (NGN)')
    max_amount = fields.Float(string='Maximum Amount (NGN)', help='0 = no upper limit')
    requires_advertisement = fields.Boolean(default=False)
    requires_prequalification = fields.Boolean(default=False)
    active = fields.Boolean(default=True)
