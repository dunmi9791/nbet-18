# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class PaymentRequest(models.Model):
    _name = 'nbet.payment.request'
    _description = 'Payment Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    contract_award_id = fields.Many2one(
        'nbet.contract.award',
        string='Contract Award',
        required=True,
        tracking=True,
        domain="[('state', '=', 'verified')]",
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Contractor/Vendor',
        related='contract_award_id.vendor_id',
        store=True,
    )
    description = fields.Char(
        related='contract_award_id.description',
        store=True,
    )
    category = fields.Selection(
        related='contract_award_id.category',
        store=True,
    )
    contract_amount = fields.Float(
        string='Contract Amount (NGN)',
        related='contract_award_id.award_amount',
        store=True,
    )
    requested_amount = fields.Float(
        string='Requested Amount (NGN)',
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted_to_md', 'Submitted to MD'),
        ('md_reviewed', 'MD Reviewed'),
        ('user_dept_review', 'User Dept Review'),
        ('user_dept_approved', 'User Dept Approved'),
        ('md_final_approval', 'MD Final Approval'),
        ('approved', 'Approved'),
        ('sent_to_treasury', 'Sent to Treasury'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
    ], default='draft', tracking=True)

    request_date = fields.Date(default=fields.Date.context_today, tracking=True)
    requested_by = fields.Many2one(
        'res.users',
        string='Requested By',
        default=lambda self: self.env.user,
        tracking=True,
    )
    department_id = fields.Many2one('hr.department', string='User Department', tracking=True)

    md_reviewer_id = fields.Many2one('res.users', string='MD Reviewer', tracking=True)
    md_review_date = fields.Date(string='MD Review Date')
    md_review_notes = fields.Text(string='MD Review Notes')

    dept_reviewer_id = fields.Many2one('res.users', string='Dept Reviewer', tracking=True)
    dept_review_date = fields.Date(string='Dept Review Date')
    dept_review_notes = fields.Text(string='Dept Review Notes')

    md_final_approver_id = fields.Many2one('res.users', string='MD Final Approver', tracking=True)
    md_final_approval_date = fields.Date(string='MD Final Approval Date')
    md_final_approval_notes = fields.Text(string='MD Final Approval Notes')

    rejection_reason = fields.Text(string='Rejection Reason')
    rejected_by = fields.Many2one('res.users', string='Rejected By')
    rejection_date = fields.Date(string='Rejection Date')

    delivery_certificate = fields.Binary(string='Delivery Certificate', attachment=True)
    delivery_certificate_filename = fields.Char()
    invoice_attachment = fields.Binary(string='Vendor Invoice', attachment=True)
    invoice_attachment_filename = fields.Char()

    payment_schedule_id = fields.Many2one(
        'nbet.payment.schedule',
        string='Payment Schedule',
        readonly=True,
    )

    notes = fields.Html()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.payment.request') or 'New'
        return super().create(vals_list)

    def action_submit_to_md(self):
        for rec in self:
            if not rec.requested_amount:
                raise UserError("Please enter the requested amount before submitting.")
            if rec.requested_amount > rec.contract_amount:
                raise UserError("Requested amount cannot exceed the contract amount.")
        self.write({
            'state': 'submitted_to_md',
            'request_date': fields.Date.context_today(self),
        })

    def action_md_review(self):
        self.write({
            'state': 'md_reviewed',
            'md_reviewer_id': self.env.user.id,
            'md_review_date': fields.Date.context_today(self),
        })

    def action_send_to_user_dept(self):
        for rec in self:
            if not rec.department_id:
                raise UserError("Please set the User Department before forwarding.")
        self.write({'state': 'user_dept_review'})

    def action_user_dept_approve(self):
        self.write({
            'state': 'user_dept_approved',
            'dept_reviewer_id': self.env.user.id,
            'dept_review_date': fields.Date.context_today(self),
        })

    def action_md_final_approve(self):
        self.write({
            'state': 'approved',
            'md_final_approver_id': self.env.user.id,
            'md_final_approval_date': fields.Date.context_today(self),
        })

    def action_send_to_treasury(self):
        for rec in self:
            schedule = self.env['nbet.payment.schedule'].create({
                'payment_request_id': rec.id,
            })
            rec.write({
                'state': 'sent_to_treasury',
                'payment_schedule_id': schedule.id,
            })
            rec.contract_award_id.write({'state': 'payment_processing'})

    def action_mark_paid(self):
        self.write({'state': 'paid'})
        for rec in self:
            rec.contract_award_id.write({'state': 'completed'})

    def action_reject(self):
        self.write({
            'state': 'rejected',
            'rejected_by': self.env.user.id,
            'rejection_date': fields.Date.context_today(self),
        })

    def action_reset_draft(self):
        self.write({
            'state': 'draft',
            'rejection_reason': False,
            'rejected_by': False,
            'rejection_date': False,
        })
