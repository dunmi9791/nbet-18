# -*- coding: utf-8 -*-
from odoo import models, fields

class NbetGencoComponentType(models.Model):
    _name = 'nbet.genco.component.type'
    _description = 'GENCO Contract Component Type'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    code = fields.Char(
        string='Code / Symbol', 
        required=True,
        help='Symbol used in python expressions (e.g., capacity_charge, energy_charge).'
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The code must be unique!')
    ]
