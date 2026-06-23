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
        # Automatically create and confirm PO
        for rec in self:
            if not rec.purchase_order_id:
                rec.action_create_purchase_order()
            if rec.purchase_order_id and rec.purchase_order_id.state == 'draft':
                # Bypass NBET approval if not already approved
                if rec.purchase_order_id.nbet_approval_state != 'approved':
                    rec.purchase_order_id.action_nbet_approve()
                rec.purchase_order_id.button_confirm()

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
        
        # Determine procurement method and product from evaluation if available
        procurement_method = False
        product_id = False
        if self.evaluation_id:
            if self.evaluation_id.procurement_method_id:
                method_code = self.evaluation_id.procurement_method_id.code
                selection_values = [v[0] for v in self.env['purchase.order']._fields['nbet_procurement_method'].selection]
                if method_code in selection_values:
                    procurement_method = method_code
            
            # Try to find a product from the procurement plan item
            if self.evaluation_id.plan_line_id and self.evaluation_id.plan_line_id.product_id:
                product_id = self.evaluation_id.plan_line_id.product_id.id

        po_vals = {
            'partner_id': self.vendor_id.id,
            'nbet_contract_award_id': self.id,
            'nbet_procurement_category': self.category,
            'nbet_procurement_method': procurement_method,
            'nbet_bid_evaluation_id': self.evaluation_id.id,
            'origin': self.name,
            'notes': self.terms_of_contract,
            'order_line': [(0, 0, {
                'name': self.description,
                'product_id': product_id,
                'product_qty': 1.0,
                'price_unit': self.award_amount,
                'date_planned': fields.Datetime.now(),
            })],
        }
        po = self.env['purchase.order'].create(po_vals)
        self.purchase_order_id = po.id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': po.id,
            'view_mode': 'form',
        }
