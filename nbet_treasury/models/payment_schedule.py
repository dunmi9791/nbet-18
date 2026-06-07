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
        ('processing', 'Processing'),
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
    approved_by = fields.Many2one('res.users', string='Approved By', tracking=True)

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

    def action_process(self):
        self.write({'state': 'processing'})

    def action_mark_paid(self):
        for rec in self:
            if not rec.payment_reference:
                raise UserError("Please enter the payment reference before marking as paid.")
        self.write({
            'state': 'paid',
            'payment_date': fields.Date.context_today(self),
            'approved_by': self.env.user.id,
        })
        for rec in self:
            rec.payment_request_id.action_mark_paid()

    def action_hold(self):
        self.write({'state': 'on_hold'})

    def action_resume(self):
        self.write({
            'state': 'scheduled',
            'hold_reason': False,
        })

    def action_cancel(self):
        self.write({'state': 'cancelled'})
