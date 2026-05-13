# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    nbet_contract_award_id = fields.Many2one(
        'nbet.contract.award',
        string='Contract Award',
    )
    nbet_procurement_category = fields.Selection([
        ('goods', 'Goods'),
        ('works', 'Works'),
        ('non_consultant', 'Non-Consultant Services'),
        ('consultant', 'Consultant Services'),
    ], string='Procurement Category')
    nbet_procurement_method = fields.Selection([
        ('shopping', 'Shopping (Market Survey)'),
        ('rfq', 'Request for Quotation'),
        ('ncb', 'National Competitive Bidding'),
        ('icb', 'International/National Competitive Bidding'),
        ('single_source', 'Single Source/Direct Contracting'),
        ('qcbs', 'Quality and Cost Based Selection'),
        ('cqs', 'Consultant Qualifications'),
        ('least_cost', 'Least Cost'),
    ], string='Procurement Method')
    nbet_approval_authority = fields.Selection([
        ('md_ceo', 'MD/CEO'),
        ('ptb', 'Parastatal Tenders Board (PTB)'),
        ('mtb', 'Ministerial Tenders Board (MTB)'),
        ('fec_bpp', 'FEC / BPP No Objection'),
    ], string='Approving Authority', compute='_compute_approval_authority', store=True)
    nbet_approval_state = fields.Selection([
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='pending', string='NBET Approval Status', tracking=True)
    nbet_approved_by = fields.Many2one('res.users', string='Approved By')
    nbet_approval_date = fields.Date(string='Approval Date')
    nbet_bid_evaluation_id = fields.Many2one(
        'nbet.bid.evaluation',
        related='nbet_contract_award_id.evaluation_id',
        string='Bid Evaluation',
        store=True,
    )
    nbet_terms_of_reference = fields.Html(string='Terms of Reference')
    nbet_inspection_done = fields.Boolean(string='Inspection Completed')
    nbet_inspection_date = fields.Date()
    nbet_inspection_notes = fields.Html(string='Inspection Notes')

    @api.depends('amount_total', 'nbet_procurement_category')
    def _compute_approval_authority(self):
        for order in self:
            if not order.nbet_procurement_category or not order.amount_total:
                order.nbet_approval_authority = False
                continue
            threshold = self.env['nbet.approval.threshold'].search([
                ('category', '=', order.nbet_procurement_category),
                ('min_amount', '<=', order.amount_total),
                '|',
                ('max_amount', '>=', order.amount_total),
                ('max_amount', '=', 0),
            ], limit=1, order='min_amount desc')
            order.nbet_approval_authority = threshold.authority if threshold else False

    def button_confirm(self):
        for order in self:
            if order.nbet_procurement_category and order.nbet_approval_state != 'approved':
                raise UserError(
                    "This purchase order requires NBET procurement approval from "
                    "the %s before it can be confirmed. Please submit for approval first."
                    % dict(self._fields['nbet_approval_authority'].selection).get(
                        order.nbet_approval_authority, 'appropriate authority'
                    )
                )
        return super().button_confirm()

    def action_nbet_approve(self):
        self.write({
            'nbet_approval_state': 'approved',
            'nbet_approved_by': self.env.user.id,
            'nbet_approval_date': fields.Date.context_today(self),
        })

    def action_nbet_reject(self):
        self.write({'nbet_approval_state': 'rejected'})

    def action_mark_inspected(self):
        self.write({
            'nbet_inspection_done': True,
            'nbet_inspection_date': fields.Date.context_today(self),
        })
