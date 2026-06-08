# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    grade_id = fields.Many2one('hr.grade', string='Grade', tracking=True)
    grade_step_id = fields.Many2one(
        'hr.grade.step', string='Step / Rank', tracking=True,
        domain="[('grade_id', '=', grade_id)]",
    )
    grade_salary = fields.Monetary(
        related='grade_step_id.amount', string='Grade Salary', readonly=True,
        currency_field='grade_currency_id',
    )
    grade_currency_id = fields.Many2one(related='grade_step_id.currency_id')

    @api.onchange('grade_id')
    def _onchange_grade_id(self):
        if self.grade_step_id and self.grade_step_id.grade_id != self.grade_id:
            self.grade_step_id = False
