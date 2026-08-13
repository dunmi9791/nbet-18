# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class BidEvaluation(models.Model):
    _name = 'nbet.bid.evaluation'
    _description = 'Bid/Quotation Evaluation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    plan_line_id = fields.Many2one('nbet.procurement.plan.line', string='Plan Item')
    request_id = fields.Many2one(
        'nbet.procurement.request',
        string='Procurement Request',
        readonly=True,
        ondelete='set null',
        copy=False,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Requesting Department',
        compute='_compute_department_id',
        store=True,
        readonly=False,
    )
    description = fields.Char(required=True)
    category = fields.Selection([
        ('goods', 'Goods'),
        ('works', 'Works'),
        ('non_consultant', 'Non-Consultant Services'),
        ('consultant', 'Consultant Services'),
    ], required=True, default='goods')
    procurement_method_id = fields.Many2one('nbet.procurement.method', string='Procurement Method')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('advertised', 'Advertised'),
        ('receiving', 'Receiving Bids'),
        ('tec_evaluation', 'TEC Evaluation'),
        ('report_submitted', 'Report Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', tracking=True)

    advertisement_date = fields.Date(string='Date Advertised')
    advertisement_newspapers = fields.Text(
        string='Newspapers / Journals',
        help='At least two national dailies required for competitive bidding',
    )
    bid_deadline = fields.Datetime(string='Bid Submission Deadline')
    bid_opening_date = fields.Datetime(string='Bid Opening Date')

    tec_chair_id = fields.Many2one('res.users', string='TEC Chairperson')
    tec_member_ids = fields.Many2many('res.users', string='TEC Members')
    actu_observer_id = fields.Many2one(
        'res.users',
        string='ACTU Observer',
        help='Anti-Corruption & Transparency Unit representative',
    )

    bid_line_ids = fields.One2many('nbet.bid.evaluation.line', 'evaluation_id', string='Bids Received')
    award_ids = fields.One2many('nbet.contract.award', 'evaluation_id', string='Contract Awards')
    evaluation_criteria = fields.Html(string='Evaluation Criteria')
    evaluation_report = fields.Html(string='Evaluation Report')
    recommended_vendor_id = fields.Many2one('res.partner', string='Recommended Vendor')
    recommended_amount = fields.Float(string='Recommended Amount (NGN)')

    approval_authority = fields.Selection([
        ('md_ceo', 'MD/CEO'),
        ('ptb', 'PTB'),
        ('mtb', 'MTB'),
        ('fec_bpp', 'FEC/BPP'),
    ], string='Approving Authority')
    approval_date = fields.Date()
    approved_by = fields.Many2one('res.users')
    notes = fields.Html()

    @api.depends('request_id.department_id', 'plan_line_id.department_id')
    def _compute_department_id(self):
        """The requesting department, from the request or -- for evaluations
        raised directly by Procurement -- from the plan item."""
        for rec in self:
            department = rec.request_id.department_id or rec.plan_line_id.department_id
            if department:
                rec.department_id = department
            elif not rec.department_id:
                rec.department_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.bid.evaluation') or 'New'
        return super().create(vals_list)

    def action_advertise(self):
        for rec in self:
            if rec.procurement_method_id and rec.procurement_method_id.requires_advertisement:
                if not rec.advertisement_newspapers:
                    raise UserError(
                        "Competitive bidding requires advertisement in at least "
                        "two national dailies. Please fill in the newspaper details."
                    )
        self.write({
            'state': 'advertised',
            'advertisement_date': fields.Date.context_today(self),
        })

    def action_start_receiving(self):
        self.write({'state': 'receiving'})

    def action_start_evaluation(self):
        for rec in self:
            if not rec.tec_chair_id:
                raise UserError("MD/CEO must constitute the Evaluation Committee before evaluation can begin.")
            if not rec.bid_line_ids:
                raise UserError("No bids have been recorded for evaluation.")
        self.write({'state': 'tec_evaluation'})

    def action_submit_report(self):
        for rec in self:
            if not rec.recommended_vendor_id:
                raise UserError("Please select a recommended vendor before submitting the report.")
        self.write({'state': 'report_submitted'})

    def action_approve(self):
        self.write({
            'state': 'approved',
            'approval_date': fields.Date.context_today(self),
            'approved_by': self.env.user.id,
        })

    def action_reject(self):
        self.write({'state': 'rejected'})
        for rec in self:
            # Hand the request back so procurement can re-tender it.
            if rec.request_id and rec.request_id.state == 'in_bidding':
                rec.request_id.sudo().write({'state': 'approved', 'bid_evaluation_id': False})
                rec.request_id.message_post(body=_(
                    'Bid evaluation %s was rejected; the request is back with '
                    'Procurement for re-tendering.', rec.name,
                ))

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_create_contract_award(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError("Bid evaluation must be approved before creating a contract award.")
        award = self.env['nbet.contract.award'].create({
            'evaluation_id': self.id,
            'vendor_id': self.recommended_vendor_id.id,
            'description': self.description,
            'category': self.category,
            'award_amount': self.recommended_amount,
        })
        if self.request_id and self.request_id.state == 'in_bidding':
            self.request_id.sudo().state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.contract.award',
            'res_id': award.id,
            'view_mode': 'form',
        }


class BidEvaluationLine(models.Model):
    _name = 'nbet.bid.evaluation.line'
    _description = 'Bid Submission'
    _order = 'bid_amount'

    evaluation_id = fields.Many2one('nbet.bid.evaluation', required=True, ondelete='cascade')
    vendor_id = fields.Many2one('res.partner', string='Bidder/Vendor', required=True)
    bid_amount = fields.Float(string='Bid Amount (NGN)', required=True)
    bid_date = fields.Datetime(string='Submission Date')
    technical_score = fields.Float(string='Technical Score (%)')
    financial_score = fields.Float(string='Financial Score (%)')
    total_score = fields.Float(compute='_compute_total_score', store=True)
    is_responsive = fields.Boolean(string='Responsive Bid', default=True)
    is_recommended = fields.Boolean(string='Recommended')
    disqualification_reason = fields.Text()
    notes = fields.Text()

    @api.depends('technical_score', 'financial_score')
    def _compute_total_score(self):
        for line in self:
            line.total_score = (line.technical_score + line.financial_score) / 2
