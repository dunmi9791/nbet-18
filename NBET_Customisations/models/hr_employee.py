# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import date

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    next_of_kin_name = fields.Char(string='Next of Kin Name')
    next_of_kin_mobile = fields.Char(string='Next of Kin Mobile')
    next_of_kin_relationship = fields.Char(string='Next of Kin Relationship')

    entry_date = fields.Date(string='Entry Date', help="Date of Employment")
    years_of_service = fields.Char(string='Years of Service', compute='_compute_years_of_service', store=True)

    @api.depends('entry_date')
    def _compute_years_of_service(self):
        today = date.today()
        for employee in self:
            if employee.entry_date:
                start_date = employee.entry_date
                years = today.year - start_date.year
                months = today.month - start_date.month
                if today.day < start_date.day:
                    months -= 1
                
                if months < 0:
                    years -= 1
                    months += 12
                
                parts = []
                if years > 0:
                    parts.append(f"{years} year{'s' if years > 1 else ''}")
                if months > 0:
                    parts.append(f"{months} month{'s' if months > 1 else ''}")
                
                if not parts:
                    employee.years_of_service = "Less than a month"
                else:
                    employee.years_of_service = " and ".join(parts)
            else:
                employee.years_of_service = "N/A"
