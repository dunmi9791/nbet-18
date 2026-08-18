# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

# Milestone states from which value is considered earned by the contractor.
EARNED_STATES = ('verified', 'payment_requested', 'paid')

# Payment request states that hold a live claim on a milestone's value.
# Drafts are excluded deliberately: nothing has been submitted yet, so an
# abandoned draft must not block a genuine claim. Two drafts racing each other
# are still caught -- whichever submits second sees the first as submitted.
CLAIMING_STATES = (
    'submitted_to_md', 'md_reviewed', 'user_dept_review',
    'user_dept_approved', 'md_final_approval', 'approved',
    'sent_to_treasury', 'paid',
)


class ContractMilestone(models.Model):
    _name = 'nbet.contract.milestone'
    _description = 'Contract Milestone'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'

    name = fields.Char(
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    title = fields.Char(
        string='Milestone',
        required=True,
        tracking=True,
        help='Short description of the deliverable, e.g. "Phase 1 - Site mobilisation".',
    )
    sequence = fields.Integer(default=10)
    contract_id = fields.Many2one(
        'nbet.contract.award',
        string='Contract',
        required=True,
        ondelete='cascade',
        index=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Contractor/Vendor',
        related='contract_id.vendor_id',
        store=True,
    )
    currency_id = fields.Many2one(
        related='contract_id.currency_id',
        readonly=True,
    )
    description = fields.Text()

    # ── Value ──────────────────────────────────────────────────────────────────
    amount_basis = fields.Selection([
        ('percent', '% of Contract Value'),
        ('fixed', 'Fixed Amount'),
    ], string='Basis', default='percent', required=True)
    percentage = fields.Float(
        string='% of Contract',
        compute='_compute_percentage',
        store=True,
        readonly=False,
    )
    amount = fields.Monetary(
        string='Milestone Value',
        compute='_compute_amount',
        store=True,
        readonly=False,
        tracking=True,
    )

    state = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('delivered', 'Delivered'),
        ('verified', 'Verified & Inspected'),
        ('payment_requested', 'Payment Requested'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], default='pending', tracking=True)

    # ── Schedule & certification ───────────────────────────────────────────────
    planned_start_date = fields.Date()
    planned_end_date = fields.Date(string='Planned Completion Date')
    actual_completion_date = fields.Date()

    ia_signoff = fields.Boolean(string='Internal Audit Sign-off')
    user_dept_signoff = fields.Boolean(string='User Dept Sign-off')
    verification_date = fields.Date(string='Inspection/Verification Date')
    verified_by = fields.Many2one('res.users', string='Verified By')
    verification_report = fields.Html(string='Verification/Inspection Report')
    deliverable_attachment = fields.Binary(string='Deliverable/Certificate', attachment=True)
    deliverable_attachment_filename = fields.Char()

    notes = fields.Html()

    # ── Links ──────────────────────────────────────────────────────────────────
    purchase_line_id = fields.Many2one(
        'purchase.order.line',
        string='Purchase Order Line',
        readonly=True,
        copy=False,
        help='The purchase order line raised for this milestone. Billing a '
             'milestone payment draws on this line only.',
    )
    payment_request_ids = fields.One2many(
        'nbet.payment.request', 'milestone_id', string='Payment Requests',
    )
    payment_request_count = fields.Integer(compute='_compute_payment_position')
    claimed_amount = fields.Monetary(
        string='Claimed',
        compute='_compute_payment_position',
        help='Value of payment requests raised against this milestone and not rejected.',
    )
    paid_amount = fields.Monetary(
        string='Paid',
        compute='_compute_payment_position',
    )

    # ── Computed values ────────────────────────────────────────────────────────
    @api.depends('amount_basis', 'percentage', 'contract_id.award_amount')
    def _compute_amount(self):
        """Derive the value from the percentage when that is the chosen basis.

        Deliberately does not depend on ``amount`` -- the pair of computes here
        would otherwise cycle. On the fixed branch the keyed-in value stands.
        """
        for milestone in self:
            if milestone.amount_basis == 'percent':
                milestone.amount = (
                    milestone.contract_id.award_amount * (milestone.percentage or 0.0) / 100.0
                )
            else:
                milestone.amount = milestone.amount or 0.0

    @api.depends('amount_basis', 'amount', 'contract_id.award_amount')
    def _compute_percentage(self):
        for milestone in self:
            total = milestone.contract_id.award_amount
            if milestone.amount_basis == 'fixed':
                milestone.percentage = (
                    milestone.amount / total * 100.0
                    if not float_is_zero(total, precision_digits=2) else 0.0
                )
            else:
                milestone.percentage = milestone.percentage or 0.0

    @api.depends('payment_request_ids.state', 'payment_request_ids.requested_amount')
    def _compute_payment_position(self):
        for milestone in self:
            requests = milestone.sudo().payment_request_ids
            claiming = requests.filtered(lambda r: r.state in CLAIMING_STATES)
            milestone.payment_request_count = len(requests)
            milestone.claimed_amount = sum(claiming.mapped('requested_amount'))
            milestone.paid_amount = sum(
                requests.filtered(lambda r: r.state == 'paid').mapped('requested_amount')
            )

    @api.constrains('amount', 'state', 'contract_id')
    def _check_milestones_within_contract_value(self):
        for milestone in self:
            contract = milestone.contract_id
            allocated = sum(
                contract.sudo().milestone_ids
                .filtered(lambda m: m.state != 'cancelled')
                .mapped('amount')
            )
            if float_compare(allocated, contract.award_amount, precision_digits=2) > 0:
                raise ValidationError(_(
                    'Milestones on contract %(contract)s total %(allocated).2f, which '
                    'exceeds the contract value of %(award).2f.',
                    contract=contract.name, allocated=allocated, award=contract.award_amount,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nbet.contract.milestone'
                ) or 'New'
        return super().create(vals_list)

    # ── Workflow ───────────────────────────────────────────────────────────────
    def action_start(self):
        for milestone in self:
            if milestone.contract_id.state not in ('agreement_signed', 'in_execution'):
                raise UserError(_(
                    'Contract %s must be signed and in execution before a milestone '
                    'can be started.', milestone.contract_id.name,
                ))
        self.write({'state': 'in_progress'})

    def action_mark_delivered(self):
        self.write({
            'state': 'delivered',
            'actual_completion_date': fields.Date.context_today(self),
        })

    def action_verify(self):
        for milestone in self:
            if not milestone.ia_signoff or not milestone.user_dept_signoff:
                raise UserError(_(
                    'Both Internal Audit and User Department sign-offs are required '
                    'before milestone "%s" can be verified.', milestone.title,
                ))
        self.write({
            'state': 'verified',
            'verification_date': fields.Date.context_today(self),
            'verified_by': self.env.user.id,
        })

    def action_request_payment(self):
        self.ensure_one()
        if self.state not in ('verified', 'payment_requested'):
            raise UserError(_(
                'Milestone "%s" must be verified before a payment can be requested.',
                self.title,
            ))
        remaining = self.amount - self.claimed_amount
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payment for %s', self.title),
            'res_model': 'nbet.payment.request',
            'view_mode': 'form',
            'context': {
                'default_contract_award_id': self.contract_id.id,
                'default_milestone_id': self.id,
                'default_requested_amount': max(remaining, 0.0),
            },
        }

    def action_view_payment_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payments for %s', self.title),
            'res_model': 'nbet.payment.request',
            'view_mode': 'list,form',
            'domain': [('milestone_id', '=', self.id)],
            'context': {
                'default_contract_award_id': self.contract_id.id,
                'default_milestone_id': self.id,
            },
        }

    def action_cancel(self):
        for milestone in self:
            if milestone.payment_request_ids.filtered(lambda r: r.state in CLAIMING_STATES):
                raise UserError(_(
                    'Milestone "%s" carries live payment requests and cannot be '
                    'cancelled. Reject those requests first.', milestone.title,
                ))
        self.write({'state': 'cancelled'})

    def action_reset_to_pending(self):
        self.write({
            'state': 'pending',
            'ia_signoff': False,
            'user_dept_signoff': False,
            'verification_date': False,
            'verified_by': False,
            'actual_completion_date': False,
        })
