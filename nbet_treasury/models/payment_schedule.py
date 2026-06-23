# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class PaymentSchedule(models.Model):
    _name = 'nbet.payment.schedule'
    _description = 'Payment Schedule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scheduled_date asc, priority desc, create_date desc'

    name = fields.Char(
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    payment_request_id = fields.Many2one(
        'nbet.payment.request',
        string='Payment Request',
        required=True,
        tracking=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Contractor/Vendor',
        related='payment_request_id.vendor_id',
        store=True,
    )
    contract_award_id = fields.Many2one(
        'nbet.contract.award',
        string='Contract Award',
        related='payment_request_id.contract_award_id',
        store=True,
    )
    description = fields.Char(
        related='payment_request_id.description',
        store=True,
    )
    amount = fields.Float(
        string='Payment Amount (NGN)',
        related='payment_request_id.requested_amount',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )

    state = fields.Selection([
        ('pending', 'Pending'),
        ('scheduled', 'Scheduled'),
        ('cfo_approved', 'CFO Approved'),
        ('fm_approved', 'Finance Manager Approved'),
        ('audited', 'Audited'),
        ('paid', 'Paid'),
        ('on_hold', 'On Hold'),
        ('cancelled', 'Cancelled'),
    ], default='pending', tracking=True)

    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'High'),
        ('2', 'Urgent'),
    ], default='0', tracking=True)

    scheduled_date = fields.Date(string='Scheduled Payment Date', tracking=True)
    payment_date = fields.Date(string='Actual Payment Date', tracking=True)
    payment_method = fields.Selection([
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('draft', 'Bank Draft'),
    ], string='Payment Method', tracking=True)
    payment_reference = fields.Char(string='Payment Reference', tracking=True)
    bank_account = fields.Char(string='Beneficiary Bank Account')

    treasury_officer_id = fields.Many2one('res.users', string='Treasury Officer', tracking=True)

    # --- Approval chain: CFO -> Finance Manager -> Auditor ---
    cfo_approved_by = fields.Many2one('res.users', string='CFO', tracking=True, copy=False)
    cfo_approval_date = fields.Date(string='CFO Approval Date', copy=False)
    cfo_notes = fields.Text(string='CFO Notes')

    fm_approved_by = fields.Many2one('res.users', string='Finance Manager', tracking=True, copy=False)
    fm_approval_date = fields.Date(string='Finance Manager Approval Date', copy=False)
    fm_notes = fields.Text(string='Finance Manager Notes')

    auditor_id = fields.Many2one('res.users', string='Auditor', tracking=True, copy=False)
    audit_date = fields.Date(string='Audit Date', copy=False)
    audit_notes = fields.Text(string='Audit Notes')

    hold_reason = fields.Text(string='Hold Reason')
    notes = fields.Html()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.payment.schedule') or 'New'
        return super().create(vals_list)

    def action_schedule(self):
        for rec in self:
            if not rec.scheduled_date:
                raise UserError("Please set a scheduled payment date.")
            if not rec.payment_method:
                raise UserError("Please select a payment method.")
        self.write({
            'state': 'scheduled',
            'treasury_officer_id': self.env.user.id,
        })

    def action_cfo_approve(self):
        for rec in self:
            if rec.state != 'scheduled':
                raise UserError("Only scheduled payments can be approved by the CFO.")
        self.write({
            'state': 'cfo_approved',
            'cfo_approved_by': self.env.user.id,
            'cfo_approval_date': fields.Date.context_today(self),
        })

    def action_fm_approve(self):
        for rec in self:
            if rec.state != 'cfo_approved':
                raise UserError("Finance Manager approval requires prior CFO approval.")
            if rec.cfo_approved_by == self.env.user:
                raise UserError(
                    "Segregation of duties: the Finance Manager approval must be "
                    "performed by a different person than the CFO."
                )
        self.write({
            'state': 'fm_approved',
            'fm_approved_by': self.env.user.id,
            'fm_approval_date': fields.Date.context_today(self),
        })

    def action_audit(self):
        for rec in self:
            if rec.state != 'fm_approved':
                raise UserError("Audit sign-off requires prior Finance Manager approval.")
            if self.env.user in (rec.cfo_approved_by | rec.fm_approved_by):
                raise UserError(
                    "Segregation of duties: the Auditor must be a different person "
                    "than the CFO and the Finance Manager."
                )
        self.write({
            'state': 'audited',
            'auditor_id': self.env.user.id,
            'audit_date': fields.Date.context_today(self),
        })

    def action_mark_paid(self):
        for rec in self:
            if rec.state != 'audited':
                raise UserError("Payment can only be processed after the Auditor's sign-off.")
            if not rec.payment_reference:
                raise UserError("Please enter the payment reference before marking as paid.")
        self.write({
            'state': 'paid',
            'payment_date': fields.Date.context_today(self),
        })
        for rec in self:
            rec.payment_request_id.write({'state': 'paid'})
            rec.payment_request_id.contract_award_id.write({
                'state': 'completed',
                'payment_date': fields.Date.context_today(self),
                'payment_reference': rec.payment_reference,
            })

    def action_reject(self):
        """Send the payment back to the treasury officer, clearing approval stamps."""
        for rec in self:
            if rec.state not in ('cfo_approved', 'fm_approved', 'audited'):
                raise UserError("Only payments in the approval chain can be rejected.")
            rec.message_post(
                body="Payment rejected by %s and returned to the treasury officer for review."
                     % self.env.user.display_name
            )
        self.write({
            'state': 'scheduled',
            'cfo_approved_by': False,
            'cfo_approval_date': False,
            'fm_approved_by': False,
            'fm_approval_date': False,
            'auditor_id': False,
            'audit_date': False,
        })

    def action_hold(self):
        self.write({'state': 'on_hold'})

    def action_resume(self):
        self.write({
            'state': 'scheduled',
            'hold_reason': False,
        })

    def action_cancel(self):
        self.write({'state': 'cancelled'})
