# -*- coding: utf-8 -*-
"""
NBET Billing Input Type Catalog
Defines the types of inputs that can be captured per billing cycle.
Seed data creates standard types (FX rates, TLF values, indices, etc.)
"""
from odoo import models, fields


class NbetBillingInputType(models.Model):
    _name = 'nbet.billing.input.type'
    _description = 'NBET Billing Input Type'
    _order = 'category, name'

    name = fields.Char(string='Input Type Name', required=True, translate=True)
    code = fields.Char(
        string='Code', required=True,
        help='Unique machine-readable code. Used as dict key in calculation service.',
    )
    category = fields.Selection(
        selection=[
            ('fx', 'FX / Exchange Rate'),
            ('index', 'Price Index'),
            ('operational', 'Operational Parameter'),
            ('loss_factor', 'Loss Factor (TLF/DLF)'),
            ('market', 'Market Parameter'),
            ('tariff', 'Tariff / Rate Reference'),
            ('misc', 'Miscellaneous'),
        ],
        string='Category', required=True,
    )
    value_type = fields.Selection(
        selection=[
            ('float', 'Decimal Number'),
            ('monetary', 'Monetary Amount'),
            ('percent', 'Percentage'),
            ('integer', 'Integer'),
            ('text', 'Text'),
            ('date', 'Date'),
        ],
        string='Value Type', required=True, default='float',
    )
    description = fields.Text(string='Description / Usage Notes')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Billing input type code must be unique.'),
    ]
