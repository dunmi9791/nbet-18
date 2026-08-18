# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_compare

from .contract_milestone import CLAIMING_STATES


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
        # A single-delivery contract must be verified in full; a milestone
        # contract is payable stage by stage while still in execution.
        domain="['|', ('state', '=', 'verified'),"
               " '&', ('execution_mode', '=', 'milestone'),"
               " ('state', 'in', ('in_execution', 'payment_processing'))]",
    )
    execution_mode = fields.Selection(
        related='contract_award_id.execution_mode',
        store=True,
    )
    milestone_id = fields.Many2one(
        'nbet.contract.milestone',
        string='Milestone',
        tracking=True,
        ondelete='restrict',
        domain="[('contract_id', '=', contract_award_id),"
               " ('state', 'in', ('verified', 'payment_requested'))]",
    )
    milestone_amount = fields.Monetary(
        string='Milestone Value',
        related='milestone_id.amount',
        store=True,
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

    notes = fields.Html()
    invoice_id = fields.Many2one('account.move', string='Vendor Bill', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.payment.request') or 'New'
        return super().create(vals_list)

    @api.onchange('contract_award_id')
    def _onchange_contract_award_id(self):
        if self.milestone_id.contract_id != self.contract_award_id:
            self.milestone_id = False

    @api.onchange('milestone_id')
    def _onchange_milestone_id(self):
        if self.milestone_id:
            self.requested_amount = max(
                self.milestone_id.amount - self.milestone_id.claimed_amount, 0.0
            )

    def _check_amount_within_envelope(self):
        """Refuse a request that would over-draw its milestone, or the contract.

        Prior non-rejected requests count against the same envelope, so a second
        full-value claim is caught rather than silently doubling the payout.
        """
        for rec in self:
            if rec.milestone_id:
                envelope = rec.milestone_id.amount
                label = _('milestone "%s"', rec.milestone_id.title)
                siblings = rec.milestone_id.sudo().payment_request_ids
            else:
                envelope = rec.contract_amount
                label = _('contract %s', rec.contract_award_id.name)
                siblings = rec.contract_award_id.sudo().payment_request_ids
            claimed = sum(
                siblings.filtered(
                    lambda r: r.id != rec.id and r.state in CLAIMING_STATES
                ).mapped('requested_amount')
            )
            if float_compare(claimed + rec.requested_amount, envelope, precision_digits=2) > 0:
                raise UserError(_(
                    'This request of %(requested).2f would take the total claimed '
                    'against %(label)s to %(total).2f, above its value of %(envelope).2f.',
                    requested=rec.requested_amount, label=label,
                    total=claimed + rec.requested_amount, envelope=envelope,
                ))

    def action_submit_to_md(self):
        for rec in self:
            if not rec.requested_amount:
                raise UserError("Please enter the requested amount before submitting.")
            if rec.execution_mode == 'milestone' and not rec.milestone_id:
                raise UserError(_(
                    'Contract %s is milestone-based. Select the milestone this '
                    'payment is being claimed against.', rec.contract_award_id.name,
                ))
            if rec.milestone_id and rec.milestone_id.contract_id != rec.contract_award_id:
                raise UserError(_(
                    'Milestone "%s" does not belong to the selected contract.',
                    rec.milestone_id.title,
                ))
        self._check_amount_within_envelope()
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
            rec.write({'state': 'sent_to_treasury'})
            rec._flag_milestone_payment_requested()

    def _flag_milestone_payment_requested(self):
        """Advance the milestone, and only move a single-delivery contract along.

        A milestone contract stays in execution so the remaining milestones can
        still be delivered and claimed.
        """
        self.ensure_one()
        if self.milestone_id and self.milestone_id.state == 'verified':
            self.milestone_id.write({'state': 'payment_requested'})
        if self.contract_award_id.execution_mode != 'milestone':
            self.contract_award_id.write({'state': 'payment_processing'})

    def action_mark_paid(self):
        self.write({'state': 'paid'})
        for rec in self:
            rec._settle_contract_position()

    def _settle_contract_position(self):
        """Close the milestone, and the contract once nothing is left outstanding."""
        self.ensure_one()
        if self.milestone_id:
            self.milestone_id.write({'state': 'paid'})
        contract = self.contract_award_id
        if contract.execution_mode != 'milestone' or contract._milestone_all_settled():
            contract.write({'state': 'completed'})

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
