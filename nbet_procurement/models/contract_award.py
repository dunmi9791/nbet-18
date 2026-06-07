# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class ContractAward(models.Model):
    _name = 'nbet.contract.award'
    _description = 'Contract Award'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    evaluation_id = fields.Many2one('nbet.bid.evaluation', string='Bid Evaluation')
    vendor_id = fields.Many2one('res.partner', string='Contractor/Vendor', required=True, tracking=True)
    description = fields.Char(required=True)
    category = fields.Selection([
        ('goods', 'Goods'),
        ('works', 'Works'),
        ('non_consultant', 'Non-Consultant Services'),
        ('consultant', 'Consultant Services'),
    ], required=True, default='goods')
    award_amount = fields.Float(string='Contract Amount (NGN)', tracking=True)
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('letter_sent', 'Award Letter Sent'),
        ('agreement_prep', 'Agreement Preparation'),
        ('agreement_signed', 'Agreement Signed'),
        ('in_execution', 'In Execution'),
        ('delivered', 'Delivered'),
        ('verified', 'Verified & Inspected'),
        ('payment_processing', 'Payment Processing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True)

    award_date = fields.Date(tracking=True)
    award_letter_date = fields.Date(string='Award Letter Date')
    agreement_date = fields.Date(string='Agreement Signing Date')
    expected_delivery_date = fields.Date()
    actual_delivery_date = fields.Date()

    verification_date = fields.Date(string='Inspection/Verification Date')
    verified_by = fields.Many2one('res.users', string='Verified By')
    verification_report = fields.Html(string='Verification/Inspection Report')
    ia_signoff = fields.Boolean(string='Internal Audit Sign-off')
    user_dept_signoff = fields.Boolean(string='User Dept Sign-off')

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order')
    payment_date = fields.Date()
    payment_reference = fields.Char()

    payment_request_ids = fields.One2many(
        'nbet.payment.request', 'contract_award_id', string='Payment Requests',
    )
    payment_request_count = fields.Integer(
        compute='_compute_payment_request_count',
    )

    terms_of_contract = fields.Html()
    notes = fields.Html()

    @api.depends('payment_request_ids')
    def _compute_payment_request_count(self):
        for rec in self:
            rec.payment_request_count = len(rec.payment_request_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.contract.award') or 'New'
        return super().create(vals_list)

    def action_send_award_letter(self):
        self.write({
            'state': 'letter_sent',
            'award_letter_date': fields.Date.context_today(self),
            'award_date': fields.Date.context_today(self),
        })

    def action_prepare_agreement(self):
        self.write({'state': 'agreement_prep'})

    def action_sign_agreement(self):
        self.write({
            'state': 'agreement_signed',
            'agreement_date': fields.Date.context_today(self),
        })

    def action_start_execution(self):
        self.write({'state': 'in_execution'})

    def action_mark_delivered(self):
        self.write({
            'state': 'delivered',
            'actual_delivery_date': fields.Date.context_today(self),
        })

    def action_verify(self):
        for rec in self:
            if not rec.ia_signoff or not rec.user_dept_signoff:
                raise UserError(
                    "Both Internal Audit and User Department sign-offs are "
                    "required before verification can be completed."
                )
        self.write({
            'state': 'verified',
            'verification_date': fields.Date.context_today(self),
            'verified_by': self.env.user.id,
        })

    def action_process_payment(self):
        self.write({'state': 'payment_processing'})

    def action_complete(self):
        self.write({'state': 'completed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_create_payment_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.payment.request',
            'view_mode': 'form',
            'context': {
                'default_contract_award_id': self.id,
                'default_requested_amount': self.award_amount,
            },
        }

    def action_view_payment_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.payment.request',
            'view_mode': 'list,form',
            'domain': [('contract_award_id', '=', self.id)],
            'context': {'default_contract_award_id': self.id},
        }

    def action_create_purchase_order(self):
        self.ensure_one()
        if not self.vendor_id:
            raise UserError("Please set a vendor before creating a purchase order.")
        po = self.env['purchase.order'].create({
            'partner_id': self.vendor_id.id,
            'nbet_contract_award_id': self.id,
            'nbet_procurement_category': self.category,
            'origin': self.name,
            'notes': self.terms_of_contract,
        })
        self.purchase_order_id = po.id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': po.id,
            'view_mode': 'form',
        }
