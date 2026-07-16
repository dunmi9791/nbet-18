# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class NeedsAssessment(models.Model):
    _name = 'nbet.needs.assessment'
    _description = 'Needs Assessment Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'fiscal_year desc, create_date desc'

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    fiscal_year = fields.Char(required=True, tracking=True)
    call_id = fields.Many2one(
        'nbet.needs.call',
        string='Needs Call',
        tracking=True,
        ondelete='set null',
        help='Annual call this submission responds to.',
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Requesting Department/Unit',
        tracking=True,
        default=lambda self: self.env.user.employee_id.department_id,
    )
    requested_by = fields.Many2one(
        'res.users',
        default=lambda self: self.env.user,
        tracking=True,
    )
    date = fields.Date(default=fields.Date.context_today, tracking=True)
    budget_allocation = fields.Float(
        string='Budget Allocation (NGN)',
        help='Budgetary appropriation from Finance & Accounts',
        tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('reviewed', 'Reviewed'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', tracking=True)
    line_ids = fields.One2many('nbet.needs.assessment.line', 'assessment_id', string='Needs')
    notes = fields.Html()
    total_estimated = fields.Float(compute='_compute_total_estimated', store=True)

    @api.depends('line_ids.estimated_cost')
    def _compute_total_estimated(self):
        for rec in self:
            rec.total_estimated = sum(rec.line_ids.mapped('estimated_cost'))

    @api.onchange('call_id')
    def _onchange_call_id(self):
        if self.call_id:
            self.fiscal_year = self.call_id.fiscal_year

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.needs.assessment') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_review(self):
        self.write({'state': 'reviewed'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})


class NeedsAssessmentLine(models.Model):
    _name = 'nbet.needs.assessment.line'
    _description = 'Needs Assessment Line'

    assessment_id = fields.Many2one('nbet.needs.assessment', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Item/Service')
    description = fields.Char(required=True)
    category = fields.Selection([
        ('goods', 'Goods'),
        ('works', 'Works'),
        ('non_consultant', 'Non-Consultant Services'),
        ('consultant', 'Consultant Services'),
    ], required=True, default='goods')
    quantity = fields.Float(default=1.0)
    estimated_unit_cost = fields.Float(string='Est. Unit Cost (NGN)')
    estimated_cost = fields.Float(
        compute='_compute_estimated_cost',
        store=True,
        string='Est. Total (NGN)',
    )
    justification = fields.Text()
    priority = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], default='medium')

    @api.depends('quantity', 'estimated_unit_cost')
    def _compute_estimated_cost(self):
        for line in self:
            line.estimated_cost = line.quantity * line.estimated_unit_cost
