# -*- coding: utf-8 -*-
"""
NBET Billing Cycle
The master control record for a monthly settlement period.
All calculations, inputs, rates, bills, and accounting documents are linked here.

State Machine:
  draft → input_loaded → calculated → reviewed → approved → posted → locked
  Any state → cancelled (admin only)
  calculated/reviewed → draft (admin only, for recompute)
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class NbetBillingCycle(models.Model):
    _name = 'nbet.billing.cycle'
    _description = 'NBET Billing Cycle'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc'

    # ── Identity ───────────────────────────────────────────────────────────────
    name = fields.Char(string='Cycle Name', required=True, tracking=True,
                       help='e.g. April 2024')
    code = fields.Char(string='Cycle Code', required=True, tracking=True,
                       help='e.g. 2024-04')
    date_start = fields.Date(string='Period Start', required=True, tracking=True)
    date_end = fields.Date(string='Period End', required=True, tracking=True)
    invoice_date = fields.Date(string='Invoice Date', tracking=True)
    hours_in_period = fields.Float(string='Hours in Period', default=720.0, tracking=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('input_loaded', 'Inputs Loaded'),
            ('calculated', 'Calculated'),
            ('reviewed', 'Reviewed'),
            ('approved', 'Approved'),
            ('posted', 'Posted'),
            ('locked', 'Locked'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft', required=True, tracking=True, index=True,
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', store=True,
    )

    # ── Period Inputs ──────────────────────────────────────────────────────────
    old_tlf = fields.Float(string='TLF Old', digits=(10, 6), tracking=True)
    new_tlf = fields.Float(string='TLF New', digits=(10, 6), tracking=True)
    fx_central_rate = fields.Float(string='CBN FX Central Rate (₦/$)', digits=(16, 4), tracking=True)
    fx_selling_rate = fields.Float(string='CBN FX Selling Rate (₦/$)', digits=(16, 4), tracking=True)
    notes = fields.Text(string='Notes')
    attachment_ids = fields.Many2many(
        'ir.attachment', string='Attachments',
        help='Upload supporting workbook, CBN rate sheets, etc.',
    )

    # ── Related Lines ──────────────────────────────────────────────────────────
    input_line_ids = fields.One2many(
        'nbet.billing.cycle.input', 'billing_cycle_id', string='Cycle Inputs',
    )
    genco_data_ids = fields.One2many(
        'nbet.genco.monthly.data', 'billing_cycle_id', string='GENCO Operational Data',
    )
    disco_data_ids = fields.One2many(
        'nbet.disco.monthly.data', 'billing_cycle_id', string='DISCO Operational Data',
    )
    rate_snapshot_ids = fields.One2many(
        'nbet.rate.snapshot', 'billing_cycle_id', string='Rate Snapshots',
    )
    expected_bill_ids = fields.One2many(
        'nbet.genco.expected.bill', 'billing_cycle_id', string='GENCO Expected Bills',
    )
    invoice_submission_ids = fields.One2many(
        'nbet.genco.invoice.submission', 'billing_cycle_id', string='GENCO Invoice Submissions',
    )
    disco_bill_ids = fields.One2many(
        'nbet.disco.bill', 'billing_cycle_id', string='DISCO Bills',
    )
    adjustment_ids = fields.One2many(
        'nbet.billing.adjustment', 'billing_cycle_id', string='Adjustments',
    )
    run_log_ids = fields.One2many(
        'nbet.billing.run.log', 'billing_cycle_id', string='Calculation Run Log',
    )

    # ── Smart Button Counts ────────────────────────────────────────────────────
    count_genco_data = fields.Integer(compute='_compute_counts', string='GENCO Data')
    count_disco_data = fields.Integer(compute='_compute_counts', string='DISCO Data')
    count_expected_bills = fields.Integer(compute='_compute_counts', string='Expected Bills')
    count_submissions = fields.Integer(compute='_compute_counts', string='Submissions')
    count_disco_bills = fields.Integer(compute='_compute_counts', string='DISCO Bills')
    count_adjustments = fields.Integer(compute='_compute_counts', string='Adjustments')
    count_accounting_moves = fields.Integer(compute='_compute_counts', string='Accounting Moves')

    def _compute_counts(self):
        for rec in self:
            rec.count_genco_data = len(rec.genco_data_ids)
            rec.count_disco_data = len(rec.disco_data_ids)
            rec.count_expected_bills = len(rec.expected_bill_ids)
            rec.count_submissions = len(rec.invoice_submission_ids)
            rec.count_disco_bills = len(rec.disco_bill_ids)
            rec.count_adjustments = len(rec.adjustment_ids)
            # Count account moves linked via GENCO bills, DISCO bills, adjustments
            move_ids = set()
            for bill in rec.expected_bill_ids:
                if hasattr(bill, 'vendor_bill_id') and bill.vendor_bill_id:
                    move_ids.add(bill.vendor_bill_id.id)
            for db in rec.disco_bill_ids:
                if db.invoice_move_id:
                    move_ids.add(db.invoice_move_id.id)
            rec.count_accounting_moves = len(move_ids)

    # ── KPI Totals ─────────────────────────────────────────────────────────────
    total_expected_genco_amount = fields.Float(
        compute='_compute_kpis', string='Total Expected GENCO', store=False,
    )
    total_submitted_genco_amount = fields.Float(
        compute='_compute_kpis', string='Total Submitted GENCO', store=False,
    )
    total_approved_genco_amount = fields.Float(
        compute='_compute_kpis', string='Total Approved GENCO', store=False,
    )
    total_disco_gross_amount = fields.Float(
        compute='_compute_kpis', string='Total DISCO Gross Bill', store=False,
    )
    total_disco_dro_payable = fields.Float(
        compute='_compute_kpis', string='Total DISCO DRO Payable', store=False,
    )
    total_subsidy_grant_exposure = fields.Float(
        compute='_compute_kpis', string='Total Subsidy/Grant Exposure', store=False,
    )
    total_variance_flagged = fields.Float(
        compute='_compute_kpis', string='Total Variance Flagged', store=False,
    )

    def _compute_kpis(self):
        for rec in self:
            rec.total_expected_genco_amount = sum(
                b.total_expected_amount for b in rec.expected_bill_ids
            )
            rec.total_submitted_genco_amount = sum(
                s.submitted_amount for s in rec.invoice_submission_ids
            )
            rec.total_approved_genco_amount = sum(
                b.total_expected_amount for b in rec.expected_bill_ids
                if b.state == 'approved'
            )
            rec.total_disco_gross_amount = sum(
                d.gross_bill_amount for d in rec.disco_bill_ids
            )
            rec.total_disco_dro_payable = sum(
                d.expected_payable_amount for d in rec.disco_bill_ids
            )
            rec.total_subsidy_grant_exposure = sum(
                d.subsidy_amount + d.grant_amount for d in rec.disco_bill_ids
            )
            rec.total_variance_flagged = sum(
                abs(s.variance_amount) for s in rec.invoice_submission_ids
                if not s.is_within_tolerance
            )

    # ── Constraints ────────────────────────────────────────────────────────────
    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)', 'Cycle code must be unique per company.'),
    ]

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError('Billing cycle end date must be after start date.')

    # ── State Guards ───────────────────────────────────────────────────────────
    def _check_not_locked(self):
        for rec in self:
            if rec.state == 'locked':
                raise UserError(
                    f'Billing cycle "{rec.name}" is locked. '
                    'Contact an Administrator to reset it.'
                )

    def _check_not_posted(self):
        for rec in self:
            if rec.state in ('posted', 'locked'):
                raise UserError(
                    f'Billing cycle "{rec.name}" is {rec.state} and cannot be modified.'
                )

    # ── State Transitions ──────────────────────────────────────────────────────
    def action_load_inputs(self):
        self._check_not_locked()
        for rec in self:
            if rec.state == 'draft':
                rec.state = 'input_loaded'
                rec.message_post(body='Inputs marked as loaded.')

    def action_compute_rates(self):
        self._check_not_locked()
        for rec in self:
            svc = self.env['nbet.calculation.service'].create({})
            svc.compute_rates_for_cycle(rec.id)

    def action_compute_genco_bills(self):
        self._check_not_locked()
        for rec in self:
            svc = self.env['nbet.calculation.service'].create({})
            svc.compute_genco_bills_for_cycle(rec.id)

    def action_compute_disco_bills(self):
        self._check_not_locked()
        for rec in self:
            svc = self.env['nbet.calculation.service'].create({})
            svc.compute_disco_bills_for_cycle(rec.id)

    def action_calculate(self):
        """Full compute: rates + GENCO bills + DISCO bills."""
        self._check_not_locked()
        for rec in self:
            svc = self.env['nbet.calculation.service'].create({})
            svc.run_for_cycle(rec.id)
            if rec.state == 'input_loaded':
                rec.state = 'calculated'

    def action_review(self):
        self._check_not_locked()
        self.write({'state': 'reviewed'})
        self.message_post(body='Cycle moved to Reviewed status.')

    def action_approve(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_settlement_manager'):
            raise UserError('Only Settlement Managers can approve billing cycles.')
        self._check_not_locked()
        self.write({'state': 'approved'})
        self.message_post(body=f'Cycle approved by {self.env.user.name}.')

    def action_post(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_accounting_officer'):
            raise UserError('Only Accounting Officers can post billing cycles.')
        for rec in self:
            if rec.state != 'approved':
                raise UserError('Billing cycle must be Approved before posting.')
            acct_svc = self.env['nbet.accounting.service'].create({})
            acct_svc.post_cycle_accounting(rec)
            rec.state = 'posted'
            rec.message_post(body=f'Accounting documents created and cycle posted by {self.env.user.name}.')

    def action_lock(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_admin'):
            raise UserError('Only NBET Administrators can lock billing cycles.')
        self.write({'state': 'locked'})
        self.message_post(body=f'Cycle locked by {self.env.user.name}.')

    def action_cancel(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_admin'):
            raise UserError('Only NBET Administrators can cancel billing cycles.')
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_admin'):
            raise UserError('Only NBET Administrators can reset billing cycles.')
        for rec in self:
            if rec.state == 'locked':
                rec.message_post(body=f'⚠ Locked cycle reset to Draft by {self.env.user.name}.')
            rec.state = 'draft'
            # Log the reset
            self.env['nbet.billing.run.log'].create({
                'billing_cycle_id': rec.id,
                'run_type': 'reset',
                'status': 'success',
                'notes': f'Cycle reset to draft by {self.env.user.name}.',
            })

    # ── Smart Button Actions ───────────────────────────────────────────────────
    def action_view_genco_data(self):
        self.ensure_one()
        return self._smart_button_action('nbet.genco.monthly.data', 'billing_cycle_id')

    def action_view_disco_data(self):
        self.ensure_one()
        return self._smart_button_action('nbet.disco.monthly.data', 'billing_cycle_id')

    def action_view_expected_bills(self):
        self.ensure_one()
        return self._smart_button_action('nbet.genco.expected.bill', 'billing_cycle_id')

    def action_view_submissions(self):
        self.ensure_one()
        return self._smart_button_action('nbet.genco.invoice.submission', 'billing_cycle_id')

    def action_view_disco_bills(self):
        self.ensure_one()
        return self._smart_button_action('nbet.disco.bill', 'billing_cycle_id')

    def action_view_adjustments(self):
        self.ensure_one()
        return self._smart_button_action('nbet.billing.adjustment', 'billing_cycle_id')

    def _smart_button_action(self, model, field):
        self.ensure_one()
        model_obj = self.env[model]
        return {
            'type': 'ir.actions.act_window',
            'name': self.env['ir.model']._get(model).name,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': [(field, '=', self.id)],
            'context': {f'default_{field}': self.id},
        }
