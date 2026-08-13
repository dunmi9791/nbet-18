# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from .procurement_request import COMMITTING_STATES


class ProcurementPlan(models.Model):
    _name = 'nbet.procurement.plan'
    _description = 'NBET Procurement Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'fiscal_year desc, create_date desc'

    name = fields.Char(
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    fiscal_year = fields.Char(required=True, tracking=True)
    call_id = fields.Many2one(
        'nbet.needs.call',
        string='Source Needs Call',
        readonly=True,
        copy=False,
        help='Annual needs call this plan was consolidated from.',
    )
    date = fields.Date(default=fields.Date.context_today, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ppc_review', 'PPC Review'),
        ('md_approval', 'MD/CEO Approval'),
        ('ptb_approval', 'PTB Approval'),
        ('approved', 'Approved'),
        ('uploaded', 'Uploaded to NOCOPO'),
        ('implementing', 'Implementing'),
        ('closed', 'Closed'),
    ], default='draft', tracking=True)

    assessment_ids = fields.Many2many(
        'nbet.needs.assessment',
        string='Needs Assessments',
        domain="[('state', '=', 'approved')]",
    )
    line_ids = fields.One2many('nbet.procurement.plan.line', 'plan_id', string='Plan Items')

    ppc_chair_id = fields.Many2one('res.users', string='PPC Chairperson (MD/CEO)')
    ppc_secretary_id = fields.Many2one('res.users', string='PPC Secretary (Head Procurement)')
    ppc_date = fields.Date(string='PPC Meeting Date')
    ppc_minutes = fields.Html(string='PPC Minutes')

    ptb_date = fields.Date(string='PTB Approval Date')
    nocopo_upload_date = fields.Date(string='NOCOPO Upload Date')
    nocopo_reference = fields.Char(string='NOCOPO Reference')

    total_budget = fields.Float(compute='_compute_totals', store=True)
    total_items = fields.Integer(compute='_compute_totals', store=True)
    total_committed = fields.Float(
        string='Total Committed',
        compute='_compute_totals',
        store=True,
        help='Value of departmental procurement requests holding budget on this plan.',
    )
    total_awarded = fields.Float(
        string='Total Awarded',
        compute='_compute_totals',
        store=True,
        help='Value of contracts actually awarded against this plan.',
    )
    total_available = fields.Float(compute='_compute_totals', store=True)
    notes = fields.Html()

    @api.depends('line_ids.estimated_amount', 'line_ids.committed_amount', 'line_ids.awarded_amount')
    def _compute_totals(self):
        for plan in self:
            plan.total_budget = sum(plan.line_ids.mapped('estimated_amount'))
            plan.total_items = len(plan.line_ids)
            plan.total_committed = sum(plan.line_ids.mapped('committed_amount'))
            plan.total_awarded = sum(plan.line_ids.mapped('awarded_amount'))
            plan.total_available = plan.total_budget - plan.total_committed

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.procurement.plan') or 'New'
        return super().create(vals_list)

    def action_submit_ppc(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError("Cannot submit a plan with no items.")
        self.write({'state': 'ppc_review'})

    def action_ppc_approve(self):
        self.write({'state': 'md_approval'})

    def action_md_approve(self):
        self.write({'state': 'ptb_approval'})

    def action_ptb_approve(self):
        self.write({'state': 'approved'})

    def action_upload_nocopo(self):
        self.write({
            'state': 'uploaded',
            'nocopo_upload_date': fields.Date.context_today(self),
        })

    def action_start_implementation(self):
        self.write({'state': 'implementing'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_populate_from_assessments(self):
        for plan in self:
            for assessment in plan.assessment_ids:
                for line in assessment.line_ids:
                    method = self._suggest_procurement_method(line.category, line.estimated_cost)
                    threshold = self._suggest_approval_authority(line.category, line.estimated_cost)
                    self.env['nbet.procurement.plan.line'].create({
                        'plan_id': plan.id,
                        'description': line.description,
                        'product_id': line.product_id.id,
                        'category': line.category,
                        'quantity': line.quantity,
                        'estimated_amount': line.estimated_cost,
                        'procurement_method_id': method.id if method else False,
                        'approval_authority': threshold.authority if threshold else False,
                        'assessment_line_id': line.id,
                        'department_id': assessment.department_id.id,
                    })

    def _suggest_procurement_method(self, category, amount):
        return self.env['nbet.procurement.method'].search([
            ('category', '=', category),
            ('min_amount', '<=', amount),
            '|',
            ('max_amount', '>=', amount),
            ('max_amount', '=', 0),
        ], limit=1, order='min_amount desc')

    def _suggest_approval_authority(self, category, amount):
        return self.env['nbet.approval.threshold'].search([
            ('category', '=', category),
            ('min_amount', '<=', amount),
            '|',
            ('max_amount', '>=', amount),
            ('max_amount', '=', 0),
        ], limit=1, order='min_amount desc')


class ProcurementPlanLine(models.Model):
    _name = 'nbet.procurement.plan.line'
    _description = 'Procurement Plan Line'

    plan_id = fields.Many2one('nbet.procurement.plan', required=True, ondelete='cascade')
    assessment_line_id = fields.Many2one('nbet.needs.assessment.line', string='Source Need')
    department_id = fields.Many2one(
        'hr.department',
        string='Owning Department/Unit',
        compute='_compute_department_id',
        store=True,
        readonly=False,
        index=True,
        help='Department this plan item belongs to. Only that department can see '
             'the item and raise procurement requests against it.',
    )
    product_id = fields.Many2one('product.product', string='Item/Service')
    description = fields.Char(required=True)
    category = fields.Selection([
        ('goods', 'Goods'),
        ('works', 'Works'),
        ('non_consultant', 'Non-Consultant Services'),
        ('consultant', 'Consultant Services'),
    ], required=True, default='goods')
    quantity = fields.Float(default=1.0)
    estimated_amount = fields.Float(string='Estimated Amount (NGN)')
    procurement_method_id = fields.Many2one('nbet.procurement.method', string='Procurement Method')
    approval_authority = fields.Selection([
        ('md_ceo', 'MD/CEO'),
        ('ptb', 'PTB'),
        ('mtb', 'MTB'),
        ('fec_bpp', 'FEC/BPP'),
    ], string='Approving Authority')
    target_quarter = fields.Selection([
        ('q1', 'Q1'),
        ('q2', 'Q2'),
        ('q3', 'Q3'),
        ('q4', 'Q4'),
    ])
    status = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], default='planned')
    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order')
    notes = fields.Text()

    request_ids = fields.One2many(
        'nbet.procurement.request', 'plan_line_id', string='Procurement Requests',
    )
    bid_evaluation_ids = fields.One2many(
        'nbet.bid.evaluation', 'plan_line_id', string='Bid Evaluations',
    )

    # ── Computed ───────────────────────────────────────────────────────────────
    display_name = fields.Char(compute='_compute_display_name', store=True)
    committed_amount = fields.Float(
        string='Committed',
        compute='_compute_budget_position',
        store=True,
        help='Reserved by departmental procurement requests from submission onward.',
    )
    awarded_amount = fields.Float(
        string='Awarded',
        compute='_compute_budget_position',
        store=True,
        help='Value of contracts actually awarded against this plan item.',
    )
    available_amount = fields.Float(
        string='Available',
        compute='_compute_budget_position',
        store=True,
    )
    utilisation_percent = fields.Float(
        string='Utilisation (%)',
        compute='_compute_budget_position',
        store=True,
    )
    request_count = fields.Integer(compute='_compute_budget_position', store=True)

    @api.depends('plan_id.name', 'description')
    def _compute_display_name(self):
        for line in self:
            line.display_name = f"[{line.plan_id.name}] {line.description}"

    @api.depends('assessment_line_id.assessment_id.department_id')
    def _compute_department_id(self):
        """Inherit the department from the need this item was consolidated from.

        Editable afterwards, and left alone for items keyed in by hand -- which
        is also what backfills existing plans on upgrade.
        """
        for line in self:
            department = line.assessment_line_id.assessment_id.department_id
            if department:
                line.department_id = department
            elif not line.department_id:
                line.department_id = False

    @api.depends(
        'estimated_amount',
        'request_ids.estimated_amount', 'request_ids.state',
        'bid_evaluation_ids.award_ids.award_amount', 'bid_evaluation_ids.award_ids.state',
    )
    def _compute_budget_position(self):
        # Read as sudo: a department submitter may only see their own
        # department's requests, but the whole envelope must be accounted for.
        for line in self:
            sudo_line = line.sudo()
            committing = sudo_line.request_ids.filtered(lambda r: r.state in COMMITTING_STATES)
            awards = sudo_line.bid_evaluation_ids.award_ids.filtered(
                lambda a: a.state != 'cancelled'
            )
            line.committed_amount = sum(committing.mapped('estimated_amount'))
            line.awarded_amount = sum(awards.mapped('award_amount'))
            line.available_amount = line.estimated_amount - line.committed_amount
            line.utilisation_percent = (
                line.committed_amount / line.estimated_amount * 100
                if not float_is_zero(line.estimated_amount, precision_digits=2) else 0.0
            )
            line.request_count = len(sudo_line.request_ids)

    @api.constrains('estimated_amount')
    def _check_estimated_amount_covers_commitments(self):
        for line in self:
            committed = sum(
                line.sudo().request_ids
                .filtered(lambda r: r.state in COMMITTING_STATES)
                .mapped('estimated_amount')
            )
            if float_compare(committed, line.estimated_amount, precision_digits=2) > 0:
                raise ValidationError(_(
                    'Plan item "%(item)s" already has %(committed).2f committed by '
                    'procurement requests; its budget cannot be reduced to %(budget).2f.',
                    item=line.description, committed=committed, budget=line.estimated_amount,
                ))

    def action_view_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Requests on %s', self.description),
            'res_model': 'nbet.procurement.request',
            'view_mode': 'list,form',
            'domain': [('plan_line_id', '=', self.id)],
            'context': {
                'default_plan_id': self.plan_id.id,
                'default_plan_line_id': self.id,
            },
        }
