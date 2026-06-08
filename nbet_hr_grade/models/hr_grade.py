# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrGrade(models.Model):
    _name = 'hr.grade'
    _description = 'Employee Salary Grade'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(string='Grade', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, tracking=True)
    sequence = fields.Integer(default=10)
    description = fields.Text()
    active = fields.Boolean(default=True, tracking=True)
    step_ids = fields.One2many('hr.grade.step', 'grade_id', string='Steps')
    step_count = fields.Integer(compute='_compute_step_count', string='Steps')
    employee_count = fields.Integer(compute='_compute_employee_count', string='Employees')
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    min_salary = fields.Monetary(
        compute='_compute_salary_range', string='Min Salary',
        currency_field='currency_id', store=True,
    )
    max_salary = fields.Monetary(
        compute='_compute_salary_range', string='Max Salary',
        currency_field='currency_id', store=True,
    )

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Grade code must be unique.'),
    ]

    @api.depends('step_ids.amount')
    def _compute_salary_range(self):
        for grade in self:
            amounts = grade.step_ids.mapped('amount')
            grade.min_salary = min(amounts) if amounts else 0.0
            grade.max_salary = max(amounts) if amounts else 0.0

    @api.depends('step_ids')
    def _compute_step_count(self):
        for grade in self:
            grade.step_count = len(grade.step_ids)

    def _compute_employee_count(self):
        data = self.env['hr.employee'].sudo()._read_group(
            [('grade_id', 'in', self.ids)],
            ['grade_id'],
            ['__count'],
        )
        mapped = {grade.id: count for grade, count in data}
        for grade in self:
            grade.employee_count = mapped.get(grade.id, 0)

    def action_view_employees(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Employees - %s', self.name),
            'res_model': 'hr.employee',
            'view_mode': 'list,form',
            'domain': [('grade_id', '=', self.id)],
        }


class HrGradeStep(models.Model):
    _name = 'hr.grade.step'
    _description = 'Grade Step / Rank'
    _inherit = ['mail.thread']
    _order = 'grade_id, sequence, name'

    name = fields.Char(string='Step / Rank', required=True, tracking=True)
    sequence = fields.Integer(default=10)
    grade_id = fields.Many2one('hr.grade', required=True, ondelete='cascade', tracking=True)
    currency_id = fields.Many2one(related='grade_id.currency_id')
    amount = fields.Monetary(
        string='Monthly Salary', required=True, tracking=True,
        currency_field='currency_id',
    )
    active = fields.Boolean(default=True, tracking=True)
    employee_count = fields.Integer(compute='_compute_employee_count', string='Employees')

    _sql_constraints = [
        ('grade_step_uniq', 'unique(grade_id, name)', 'Step name must be unique within a grade.'),
    ]

    @api.constrains('amount')
    def _check_amount(self):
        for step in self:
            if step.amount < 0:
                raise ValidationError(_('Salary amount cannot be negative.'))

    def _compute_employee_count(self):
        data = self.env['hr.employee'].sudo()._read_group(
            [('grade_step_id', 'in', self.ids)],
            ['grade_step_id'],
            ['__count'],
        )
        mapped = {step.id: count for step, count in data}
        for step in self:
            step.employee_count = mapped.get(step.id, 0)

    def name_get(self):
        return [(s.id, f"{s.grade_id.name} / {s.name}") for s in self]
