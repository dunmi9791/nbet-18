# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

# States in which a request holds (reserves) budget on its procurement plan
# item. A request reserves from submission onward -- not only once approved --
# so two departments cannot both spend the same envelope while their requests
# sit in the approval chain.
COMMITTING_STATES = (
    'dept_approval',
    'procurement_review',
    'authority_approval',
    'approved',
    'in_bidding',
    'done',
)

CATEGORY_SELECTION = [
    ('goods', 'Goods'),
    ('works', 'Works'),
    ('non_consultant', 'Non-Consultant Services'),
    ('consultant', 'Consultant Services'),
]


class ProcurementRequest(models.Model):
    _name = 'nbet.procurement.request'
    _description = 'Departmental Procurement Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, create_date desc'

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    title = fields.Char(
        required=True,
        tracking=True,
        help='Short subject of the expense or project being requested.',
    )
    request_type = fields.Selection([
        ('expense', 'Operational Expense'),
        ('project', 'Project'),
    ], required=True, default='expense', tracking=True)
    department_id = fields.Many2one(
        'hr.department',
        string='Requesting Department/Unit',
        required=True,
        tracking=True,
        default=lambda self: self.env.user.employee_id.department_id,
    )
    requested_by = fields.Many2one(
        'res.users',
        default=lambda self: self.env.user,
        tracking=True,
    )
    date = fields.Date(default=fields.Date.context_today, tracking=True)

    # ── Plan linkage ───────────────────────────────────────────────────────────
    plan_id = fields.Many2one(
        'nbet.procurement.plan',
        string='Procurement Plan',
        tracking=True,
        domain="[('state', 'in', ('approved', 'uploaded', 'implementing'))]",
    )
    plan_line_id = fields.Many2one(
        'nbet.procurement.plan.line',
        string='Plan Item',
        tracking=True,
        ondelete='restrict',
        domain="[('plan_id', '=', plan_id), ('department_id', '=', department_id)]",
        help='Approved plan item this request draws its budget from.',
    )
    fiscal_year = fields.Char(related='plan_id.fiscal_year', store=True, readonly=True)
    is_unplanned = fields.Boolean(
        string='Unplanned / Emergency',
        tracking=True,
        help='Procurement not covered by any approved plan item. Requires '
             'justification and always goes to the approving authority.',
    )
    unplanned_justification = fields.Text(string='Emergency Justification')

    category = fields.Selection(CATEGORY_SELECTION, required=True, default='goods')
    line_ids = fields.One2many('nbet.procurement.request.line', 'request_id', string='Requested Items')
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    estimated_amount = fields.Monetary(
        string='Estimated Amount',
        compute='_compute_estimated_amount',
        store=True,
        tracking=True,
    )

    procurement_method_id = fields.Many2one(
        'nbet.procurement.method',
        string='Procurement Method',
        compute='_compute_procurement_routing',
        store=True,
        readonly=False,
    )
    approval_authority = fields.Selection([
        ('md_ceo', 'MD/CEO'),
        ('ptb', 'PTB'),
        ('mtb', 'MTB'),
        ('fec_bpp', 'FEC/BPP'),
    ], string='Approving Authority',
        compute='_compute_procurement_routing',
        store=True,
        readonly=False,
    )

    justification = fields.Text(required=True)
    notes = fields.Html()

    state = fields.Selection([
        ('draft', 'Draft'),
        ('dept_approval', 'Department Approval'),
        ('procurement_review', 'Procurement Review'),
        ('authority_approval', 'Authority Approval'),
        ('approved', 'Approved'),
        ('in_bidding', 'In Bid Evaluation'),
        ('done', 'Awarded'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True)

    dept_approver_id = fields.Many2one('res.users', string='Department Approver', readonly=True)
    dept_approval_date = fields.Date(string='Department Approval Date', readonly=True)
    proc_approver_id = fields.Many2one('res.users', string='Procurement Reviewer', readonly=True)
    proc_approval_date = fields.Date(string='Procurement Review Date', readonly=True)
    authority_approver_id = fields.Many2one('res.users', string='Authority Approver', readonly=True)
    authority_approval_date = fields.Date(string='Authority Approval Date', readonly=True)
    rejection_reason = fields.Text(tracking=True)

    bid_evaluation_id = fields.Many2one(
        'nbet.bid.evaluation',
        string='Bid Evaluation',
        readonly=True,
        copy=False,
    )
    bid_evaluation_state = fields.Selection(
        related='bid_evaluation_id.state',
        string='Bid Evaluation Status',
        readonly=True,
    )

    # ── Live budget position of the plan item ──────────────────────────────────
    plan_line_budget = fields.Monetary(
        string='Plan Item Budget',
        compute='_compute_plan_line_budget',
    )
    plan_line_committed_other = fields.Monetary(
        string='Committed by Other Requests',
        compute='_compute_plan_line_budget',
    )
    plan_line_awarded = fields.Monetary(
        string='Actually Awarded',
        compute='_compute_plan_line_budget',
    )
    plan_line_available = fields.Monetary(
        string='Available',
        compute='_compute_plan_line_budget',
    )
    plan_line_utilisation = fields.Float(
        string='Plan Item Utilisation (%)',
        compute='_compute_plan_line_budget',
    )

    # ── Computes ───────────────────────────────────────────────────────────────
    @api.depends('line_ids.estimated_cost')
    def _compute_estimated_amount(self):
        for rec in self:
            rec.estimated_amount = sum(rec.line_ids.mapped('estimated_cost'))

    @api.depends('category', 'estimated_amount')
    def _compute_procurement_routing(self):
        Plan = self.env['nbet.procurement.plan']
        for rec in self:
            method = Plan._suggest_procurement_method(rec.category, rec.estimated_amount)
            threshold = Plan._suggest_approval_authority(rec.category, rec.estimated_amount)
            rec.procurement_method_id = method.id if method else False
            rec.approval_authority = threshold.authority if threshold else False

    @api.depends('plan_line_id', 'estimated_amount')
    def _compute_plan_line_budget(self):
        for rec in self:
            line = rec.plan_line_id
            budget = line.estimated_amount if line else 0.0
            committed_other = rec._committed_by_siblings()
            awarded = line.sudo().awarded_amount if line else 0.0
            rec.plan_line_budget = budget
            rec.plan_line_committed_other = committed_other
            rec.plan_line_awarded = awarded
            rec.plan_line_available = budget - committed_other
            rec.plan_line_utilisation = (
                (committed_other + rec.estimated_amount) / budget * 100
                if not float_is_zero(budget, precision_digits=2) else 0.0
            )

    def _committed_by_siblings(self):
        """Amount already reserved on this request's plan item by *other* requests.

        Read as sudo: a department submitter cannot see other departments'
        requests, but the envelope they consume must still be accounted for.
        """
        self.ensure_one()
        if not self.plan_line_id:
            return 0.0
        siblings = self.sudo().search([
            ('plan_line_id', '=', self.plan_line_id.id),
            ('state', 'in', COMMITTING_STATES),
            ('id', '!=', self._origin.id or 0),
        ])
        return sum(siblings.mapped('estimated_amount'))

    # ── Constraints ────────────────────────────────────────────────────────────
    @api.constrains('plan_line_id', 'estimated_amount', 'state', 'is_unplanned')
    def _check_plan_line_budget(self):
        for rec in self:
            if rec.is_unplanned or not rec.plan_line_id or rec.state not in COMMITTING_STATES:
                continue
            budget = rec.plan_line_id.estimated_amount
            committed_other = rec._committed_by_siblings()
            total = committed_other + rec.estimated_amount
            if float_compare(total, budget, precision_digits=2) > 0:
                raise ValidationError(_(
                    'This request exceeds the approved budget of plan item '
                    '"%(item)s".\n\n'
                    'Plan item budget:            %(budget).2f\n'
                    'Already committed:           %(committed).2f\n'
                    'Available:                   %(available).2f\n'
                    'This request:                %(requested).2f\n\n'
                    'Reduce the requested items, or raise it as an unplanned '
                    'procurement for the approving authority to consider.',
                    item=rec.plan_line_id.display_name,
                    budget=budget,
                    committed=committed_other,
                    available=budget - committed_other,
                    requested=rec.estimated_amount,
                ))

    @api.constrains('plan_line_id', 'plan_id', 'is_unplanned', 'unplanned_justification')
    def _check_plan_linkage(self):
        for rec in self:
            if rec.is_unplanned:
                if not rec.unplanned_justification:
                    raise ValidationError(_(
                        'An unplanned/emergency request must state why the item '
                        'could not be planned for.'
                    ))
            elif not rec.plan_line_id:
                raise ValidationError(_(
                    'Select the procurement plan item this request draws from, '
                    'or tick "Unplanned / Emergency".'
                ))
            if rec.plan_line_id and rec.plan_id and rec.plan_line_id.plan_id != rec.plan_id:
                raise ValidationError(_(
                    'The selected plan item does not belong to plan %s.',
                    rec.plan_id.name,
                ))
            if rec.plan_line_id and rec.plan_line_id.sudo().department_id != rec.department_id:
                raise ValidationError(_(
                    'Plan item "%(item)s" belongs to %(owner)s. %(dept)s cannot '
                    'draw from another department\'s budget.',
                    item=rec.plan_line_id.sudo().display_name,
                    owner=rec.plan_line_id.sudo().department_id.name or _('no department'),
                    dept=rec.department_id.name,
                ))

    # ── Onchange helpers ───────────────────────────────────────────────────────
    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        if self.plan_line_id:
            self.plan_id = self.plan_line_id.plan_id
            self.category = self.plan_line_id.category

    @api.onchange('department_id')
    def _onchange_department_id(self):
        if self.plan_line_id and self.plan_line_id.department_id != self.department_id:
            self.plan_line_id = False

    @api.onchange('is_unplanned')
    def _onchange_is_unplanned(self):
        if self.is_unplanned:
            self.plan_line_id = False

    @api.onchange('plan_line_id', 'line_ids')
    def _onchange_warn_over_budget(self):
        """Warn while still in draft -- draft reserves nothing, so the hard
        constraint stays silent until the request is submitted."""
        if self.is_unplanned or not self.plan_line_id or self.state != 'draft':
            return
        available = self.plan_line_budget - self.plan_line_committed_other
        if float_compare(self.estimated_amount, available, precision_digits=2) > 0:
            return {'warning': {
                'title': _('Over plan item budget'),
                'message': _(
                    'Plan item "%(item)s" has %(available).2f left, but this '
                    'request comes to %(requested).2f. You will not be able to '
                    'submit it until it fits.',
                    item=self.plan_line_id.display_name,
                    available=available,
                    requested=self.estimated_amount,
                ),
            }}

    # ── CRUD ───────────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.procurement.request') or 'New'
        return super().create(vals_list)

    def unlink(self):
        for rec in self:
            if rec.state not in ('draft', 'cancelled'):
                raise UserError(_(
                    'Request %s can no longer be deleted; cancel it instead.',
                    rec.name,
                ))
        return super().unlink()

    # ── Workflow ───────────────────────────────────────────────────────────────
    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Add at least one item before submitting this request.'))
            if float_is_zero(rec.estimated_amount, precision_digits=2):
                raise UserError(_('The requested items come to zero. Enter the estimated costs.'))
        self.write({'state': 'dept_approval'})
        for rec in self:
            rec._notify_department_head()

    def action_dept_approve(self):
        self.write({
            'state': 'procurement_review',
            'dept_approver_id': self.env.user.id,
            'dept_approval_date': fields.Date.context_today(self),
        })

    def action_procurement_approve(self):
        floor = float(self.env['ir.config_parameter'].sudo().get_param(
            'nbet_procurement.request_authority_min_amount', 0.0,
        ) or 0.0)
        for rec in self:
            needs_authority = (
                rec.is_unplanned
                or float_compare(rec.estimated_amount, floor, precision_digits=2) >= 0
            )
            rec.write({
                'state': 'authority_approval' if needs_authority else 'approved',
                'proc_approver_id': self.env.user.id,
                'proc_approval_date': fields.Date.context_today(rec),
            })

    def action_authority_approve(self):
        self.write({
            'state': 'approved',
            'authority_approver_id': self.env.user.id,
            'authority_approval_date': fields.Date.context_today(self),
        })

    def action_reject(self):
        for rec in self:
            if not rec.rejection_reason:
                raise UserError(_('State the reason for rejecting this request.'))
        self.write({'state': 'rejected'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_create_bid_evaluation(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Only an approved request can go to bid evaluation.'))
        if self.bid_evaluation_id:
            raise UserError(_('This request is already linked to bid evaluation %s.',
                              self.bid_evaluation_id.name))
        evaluation = self.env['nbet.bid.evaluation'].create({
            'request_id': self.id,
            'plan_line_id': self.plan_line_id.id,
            'description': self.title,
            'category': self.category,
            'procurement_method_id': self.procurement_method_id.id,
            'approval_authority': self.approval_authority,
        })
        self.write({'state': 'in_bidding', 'bid_evaluation_id': evaluation.id})
        if self.plan_line_id and self.plan_line_id.status == 'planned':
            self.plan_line_id.sudo().status = 'in_progress'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.bid.evaluation',
            'res_id': evaluation.id,
            'view_mode': 'form',
        }

    def action_view_bid_evaluation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.bid.evaluation',
            'res_id': self.bid_evaluation_id.id,
            'view_mode': 'form',
        }

    # ── Notifications ──────────────────────────────────────────────────────────
    def _notify_department_head(self):
        self.ensure_one()
        user = self.department_id.manager_id.user_id
        if not user or user == self.env.user:
            return
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary=_('Approve procurement request %s', self.name),
            note=_('%(requester)s has raised a procurement request for '
                   '%(amount).2f. Please review and endorse it.',
                   requester=self.requested_by.name, amount=self.estimated_amount),
            user_id=user.id,
        )
        self.message_notify(
            partner_ids=user.partner_id.ids,
            subject=_('Procurement Request %s awaiting your approval', self.name),
            body=_(
                '<p>Dear %(name)s,</p>'
                '<p><strong>%(requester)s</strong> has raised procurement request '
                '<strong>%(ref)s</strong> — %(title)s — for %(amount).2f.</p>'
                '<p>Please review and endorse it so it can move to the '
                'Procurement Department.</p>',
                name=user.name, requester=self.requested_by.name,
                ref=self.name, title=self.title, amount=self.estimated_amount,
            ),
        )


class ProcurementRequestLine(models.Model):
    _name = 'nbet.procurement.request.line'
    _description = 'Procurement Request Line'

    request_id = fields.Many2one('nbet.procurement.request', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='request_id.currency_id', readonly=True)
    product_id = fields.Many2one('product.product', string='Item/Service')
    description = fields.Char(required=True)
    quantity = fields.Float(default=1.0)
    estimated_unit_cost = fields.Monetary(string='Est. Unit Cost')
    estimated_cost = fields.Monetary(
        compute='_compute_estimated_cost',
        store=True,
        string='Est. Total',
    )
    justification = fields.Text()

    @api.depends('quantity', 'estimated_unit_cost')
    def _compute_estimated_cost(self):
        for line in self:
            line.estimated_cost = line.quantity * line.estimated_unit_cost

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and not self.description:
            self.description = self.product_id.display_name
