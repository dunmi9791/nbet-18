# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrContract(models.Model):
    _inherit = 'hr.contract'

    grade_id = fields.Many2one(
        related='employee_id.grade_id', string='Grade',
        readonly=True, store=True,
    )
    grade_step_id = fields.Many2one(
        related='employee_id.grade_step_id', string='Step / Rank',
        readonly=True, store=True,
    )

    @api.onchange('employee_id')
    def _onchange_employee_grade(self):
        if self.employee_id and self.employee_id.grade_step_id:
            self.wage = self.employee_id.grade_step_id.amount

    def action_sync_wage_from_grade(self):
        for contract in self:
            if contract.employee_id.grade_step_id:
                contract.wage = contract.employee_id.grade_step_id.amount
