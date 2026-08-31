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
    move_ids = fields.One2many(
        'account.move', 'nbet_billing_cycle_id', string='Accounting Documents',
    )
    payment_ids = fields.Many2many(
        'account.payment', string='Settlement Payments',
        compute='_compute_payment_ids',
        help='Payments reconciled against the invoices and bills of this cycle.',
    )
    payment_advice_ids = fields.One2many(
        'nbet.payment.advice', 'billing_cycle_id', string='Payment Advices',
    )
    collection_advice_ids = fields.One2many(
        'nbet.collection.advice', 'billing_cycle_id',
        string='Collection Advices',
    )

    # ── Smart Button Counts ────────────────────────────────────────────────────
    count_genco_data = fields.Integer(compute='_compute_counts', string='GENCO Data')
    count_disco_data = fields.Integer(compute='_compute_counts', string='DISCO Data')
    count_expected_bills = fields.Integer(compute='_compute_counts', string='Expected Bills')
    count_submissions = fields.Integer(compute='_compute_counts', string='Submissions')
    count_disco_bills = fields.Integer(compute='_compute_counts', string='DISCO Bills')
    count_adjustments = fields.Integer(compute='_compute_counts', string='Adjustments')
    count_accounting_moves = fields.Integer(compute='_compute_counts', string='Accounting Moves')
    count_disco_invoices = fields.Integer(compute='_compute_counts', string='DISCO Invoices')
    count_genco_vendor_bills = fields.Integer(compute='_compute_counts', string='GENCO Vendor Bills')
    count_payments = fields.Integer(compute='_compute_payment_ids', string='Payments')
    count_payment_advices = fields.Integer(compute='_compute_counts', string='Payment Advices')
    count_collection_advices = fields.Integer(compute='_compute_counts', string='Collection Advices')

    def _compute_counts(self):
        for rec in self:
            rec.count_genco_data = len(rec.genco_data_ids)
            rec.count_disco_data = len(rec.disco_data_ids)
            rec.count_expected_bills = len(rec.expected_bill_ids)
            rec.count_submissions = len(rec.invoice_submission_ids)
            rec.count_disco_bills = len(rec.disco_bill_ids)
            rec.count_adjustments = len(rec.adjustment_ids)
            rec.count_accounting_moves = len(rec.move_ids)
            rec.count_disco_invoices = len(rec._get_receivable_moves(posted_only=False))
            rec.count_genco_vendor_bills = len(rec._get_payable_moves(posted_only=False))
            rec.count_payment_advices = len(rec.payment_advice_ids)
            rec.count_collection_advices = len(rec.collection_advice_ids)

    @api.depends('move_ids', 'move_ids.matched_payment_ids')
    def _compute_payment_ids(self):
        for rec in self:
            payments = rec.move_ids.matched_payment_ids
            rec.payment_ids = payments
            rec.count_payments = len(payments)

    # ── Settlement Document Selectors ──────────────────────────────────────────
    def _get_receivable_moves(self, posted_only=True):
        """Customer invoices / credit notes billed to DISCOs for this cycle."""
        self.ensure_one()
        return self.move_ids.filtered(
            lambda m: m.move_type in ('out_invoice', 'out_refund')
            and (m.state == 'posted' if posted_only else m.state != 'cancel')
        )

    def _get_payable_moves(self, posted_only=True):
        """Vendor bills / refunds owed to GENCOs for this cycle."""
        self.ensure_one()
        return self.move_ids.filtered(
            lambda m: m.move_type in ('in_invoice', 'in_refund')
            and (m.state == 'posted' if posted_only else m.state != 'cancel')
        )

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

    # ── Cash Position (mini dashboard) ─────────────────────────────────────────
    total_disco_invoiced = fields.Monetary(
        compute='_compute_cash_position', string='Total Invoiced to DISCOs',
        currency_field='currency_id',
        help='Posted customer invoices raised on DISCOs for this cycle, net of credit notes.',
    )
    total_genco_billed = fields.Monetary(
        compute='_compute_cash_position', string='Total Billed by GENCOs',
        currency_field='currency_id',
        help='Posted vendor bills received from GENCOs for this cycle, net of refunds.',
    )
    total_payment_received = fields.Monetary(
        compute='_compute_cash_position', string='Payments Received',
        currency_field='currency_id',
        help='Cash received from DISCOs against this cycle’s invoices.',
    )
    total_payment_made = fields.Monetary(
        compute='_compute_cash_position', string='Payments Made',
        currency_field='currency_id',
        help='Cash paid to GENCOs against this cycle’s vendor bills.',
    )
    net_payment_difference = fields.Monetary(
        compute='_compute_cash_position', string='Difference (Received − Paid)',
        currency_field='currency_id',
    )
    total_receivable_outstanding = fields.Monetary(
        compute='_compute_cash_position', string='Outstanding from DISCOs',
        currency_field='currency_id',
    )
    total_payable_outstanding = fields.Monetary(
        compute='_compute_cash_position', string='Outstanding to GENCOs',
        currency_field='currency_id',
    )
    collection_rate_percent = fields.Float(
        compute='_compute_cash_position', string='Collection Rate (%)', digits=(5, 2),
    )
    settlement_rate_percent = fields.Float(
        compute='_compute_cash_position', string='Settlement Rate (%)', digits=(5, 2),
    )

    @api.depends('move_ids.amount_total', 'move_ids.amount_residual',
                 'move_ids.state', 'move_ids.move_type', 'move_ids.currency_id')
    def _compute_cash_position(self):
        for rec in self:
            receivables = rec._get_receivable_moves()
            payables = rec._get_payable_moves()

            rec.total_disco_invoiced = sum(m._nbet_total_amount() for m in receivables)
            rec.total_genco_billed = sum(m._nbet_total_amount() for m in payables)
            rec.total_payment_received = sum(m._nbet_settled_amount() for m in receivables)
            rec.total_payment_made = sum(m._nbet_settled_amount() for m in payables)
            rec.net_payment_difference = rec.total_payment_received - rec.total_payment_made
            rec.total_receivable_outstanding = sum(m._nbet_open_amount() for m in receivables)
            rec.total_payable_outstanding = sum(m._nbet_open_amount() for m in payables)
            rec.collection_rate_percent = (
                rec.total_payment_received / rec.total_disco_invoiced * 100.0
                if rec.total_disco_invoiced else 0.0
            )
            rec.settlement_rate_percent = (
                rec.total_payment_made / rec.total_genco_billed * 100.0
                if rec.total_genco_billed else 0.0
            )

    # ── Meristem Collections Position ──────────────────────────────────────────
    total_collection_advised = fields.Monetary(
        compute='_compute_collection_position', string='Collections Advised',
        currency_field='currency_id',
        help='Total advised by Meristem for this cycle across all collection advices.',
    )
    total_collection_in_bank = fields.Monetary(
        compute='_compute_collection_position', string='Collections in Bank',
        currency_field='currency_id',
        help='Advised amounts finance has confirmed in the bank.',
    )
    total_collection_with_remita = fields.Monetary(
        compute='_compute_collection_position', string='Collections with Remita',
        currency_field='currency_id',
        help='Advised amounts still with Remita, not yet at the bank.',
    )
    total_collection_not_seen = fields.Monetary(
        compute='_compute_collection_position', string='Collections Not Seen',
        currency_field='currency_id',
        help='Advised amounts finance checked for and found nowhere.',
    )
    collection_confirmed_percent = fields.Float(
        compute='_compute_collection_position',
        string='Confirmed in Bank (%)', digits=(5, 2),
    )

    @api.depends('collection_advice_ids.state',
                 'collection_advice_ids.total_advised',
                 'collection_advice_ids.total_in_bank',
                 'collection_advice_ids.total_with_remita',
                 'collection_advice_ids.total_not_seen')
    def _compute_collection_position(self):
        for rec in self:
            advices = rec.collection_advice_ids.filtered(
                lambda a: a.state != 'cancelled')
            rec.total_collection_advised = sum(advices.mapped('total_advised'))
            rec.total_collection_in_bank = sum(advices.mapped('total_in_bank'))
            rec.total_collection_with_remita = sum(
                advices.mapped('total_with_remita'))
            rec.total_collection_not_seen = sum(
                advices.mapped('total_not_seen'))
            rec.collection_confirmed_percent = (
                rec.total_collection_in_bank / rec.total_collection_advised * 100.0
                if rec.total_collection_advised else 0.0
            )

    # ── Constraints ────────────────────────────────────────────────────────────
    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)', 'Cycle code must be unique per company.'),
    ]

    @api.ondelete(at_uninstall=False)
    def _unlink_except_linked_moves(self):
        for rec in self:
            if rec.move_ids:
                raise UserError(
                    f'Billing cycle "{rec.name}" cannot be deleted: '
                    f'{len(rec.move_ids)} accounting document(s) are linked to it. '
                    'Cancel and unlink those documents first.'
                )

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
        if not self.env.user.has_group('nbet_power_billing.group_nbet_billing_reviewer'):
            raise UserError('Only Billing Reviewers can mark billing cycles as reviewed.')
        self._check_not_locked()
        for rec in self:
            if rec.state != 'calculated':
                raise UserError('Billing cycle must be Calculated before it can be reviewed.')
            rec.state = 'reviewed'
            rec.message_post(body=f'Cycle reviewed by {self.env.user.name}.')

    def action_approve(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_settlement_manager'):
            raise UserError('Only Settlement Managers can approve billing cycles.')
        self._check_not_locked()
        for rec in self:
            if rec.state != 'reviewed':
                raise UserError('Billing cycle must be Reviewed before it can be approved.')
            rec.state = 'approved'
            rec.message_post(body=f'Cycle approved by {self.env.user.name}.')

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

    def action_view_payment_advices(self):
        self.ensure_one()
        return self._smart_button_action('nbet.payment.advice', 'billing_cycle_id')

    def action_view_collection_advices(self):
        self.ensure_one()
        return self._smart_button_action('nbet.collection.advice', 'billing_cycle_id')

    def action_view_disco_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'DISCO Invoices — {self.name}',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('nbet_billing_cycle_id', '=', self.id),
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('state', '!=', 'cancel'),
            ],
            'context': {
                'default_move_type': 'out_invoice',
                'default_nbet_billing_cycle_id': self.id,
            },
        }

    def action_view_genco_vendor_bills(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'GENCO Vendor Bills — {self.name}',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('nbet_billing_cycle_id', '=', self.id),
                ('move_type', 'in', ('in_invoice', 'in_refund')),
                ('state', '!=', 'cancel'),
            ],
            'context': {
                'default_move_type': 'in_invoice',
                'default_nbet_billing_cycle_id': self.id,
            },
        }

    def action_view_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Settlement Payments — {self.name}',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.payment_ids.ids)],
        }

    # ── Document Linking ───────────────────────────────────────────────────────
    def action_sync_settlement_documents(self):
        """Stamp the cycle link onto accounting documents that are reachable
        from this cycle's bills but not yet linked.

        Covers documents created before the cycle link existed, and any move
        attached manually to a GENCO/DISCO bill.
        """
        for rec in self:
            linked = 0
            for bill in rec.expected_bill_ids:
                linked += rec._stamp_move(
                    bill.vendor_bill_id, bill.participant_id, 'genco')
            for sub in rec.invoice_submission_ids:
                linked += rec._stamp_move(
                    sub.vendor_bill_id, sub.participant_id, 'genco')
            for disco_bill in rec.disco_bill_ids:
                linked += rec._stamp_move(
                    disco_bill.invoice_move_id, disco_bill.participant_id, 'disco')
            for adj in rec.adjustment_ids:
                linked += rec._stamp_move(
                    adj.journal_entry_id, adj.participant_id, 'adjustment')
            rec.message_post(
                body=f'Settlement document sync: {linked} accounting document(s) '
                     f'linked to this billing cycle.'
            )
        return True

    def _stamp_move(self, move, participant, role):
        """Link a move to this cycle. Returns 1 if it was newly linked."""
        self.ensure_one()
        if not move:
            return 0
        if move.nbet_billing_cycle_id and move.nbet_billing_cycle_id != self:
            raise UserError(
                f'{move.name or "Draft document"} is already linked to billing '
                f'cycle "{move.nbet_billing_cycle_id.name}". Unlink it there first.'
            )
        vals = {}
        if not move.nbet_billing_cycle_id:
            vals['nbet_billing_cycle_id'] = self.id
        if participant and not move.nbet_participant_id:
            vals['nbet_participant_id'] = participant.id
        if role and not move.nbet_settlement_role:
            vals['nbet_settlement_role'] = role
        if not vals:
            return 0
        # Stamping the settlement link is bookkeeping metadata, not an edit of
        # the document itself — don't flag the move as manually modified.
        move.sudo().with_context(skip_is_manually_modified=True).write(vals)
        return 1 if 'nbet_billing_cycle_id' in vals else 0

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
