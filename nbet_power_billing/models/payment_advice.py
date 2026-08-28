# -*- coding: utf-8 -*-
"""
NBET GENCO Payment Advice
After the Payment Committee meeting, the collections received from DISCOs on a
posted billing cycle are shared out to the GENCOs. The advice lists each GENCO
and the amount it will be paid, suggested pro-rata to its outstanding vendor
bill balance and adjustable to what the committee decided.

State Machine:
  draft → submitted → ocma_approved → md_approved → sent_to_treasury → paid
  submitted/ocma_approved → rejected → draft
  Any pre-treasury state → cancelled (settlement manager)

The last two states are reached through the nbet_billing_treasury bridge, which
hands the advice to the treasury payment schedule.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare, float_round


class NbetPaymentAdvice(models.Model):
    _name = 'nbet.payment.advice'
    _description = 'NBET GENCO Payment Advice'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ── Identity ───────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Advice Number', required=True, readonly=True,
        default='New', copy=False,
    )
    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle', required=True,
        ondelete='restrict', index=True, tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', related='billing_cycle_id.company_id', store=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='billing_cycle_id.currency_id', store=True,
    )
    advice_date = fields.Date(
        string='Advice Date', default=fields.Date.context_today, tracking=True,
    )
    committee_date = fields.Date(
        string='Committee Meeting Date', tracking=True,
        help='Date of the Payment Committee meeting this advice implements.',
    )
    committee_reference = fields.Char(
        string='Committee Reference',
        help='Minute or memo reference of the committee decision.',
    )
    notes = fields.Text(string='Notes')

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('ocma_approved', 'OCMA Approved'),
            ('md_approved', 'MD Approved'),
            ('sent_to_treasury', 'With Treasury'),
            ('paid', 'Paid'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft', required=True, tracking=True, index=True, copy=False,
    )

    # ── Collections pool (frozen at snapshot time) ─────────────────────────────
    # total_payment_received on the cycle is a non-stored compute derived from
    # reconciliation, so the figures the committee decided on are copied here
    # and kept — the same "frozen at compute time" idiom as the DISCO DRO.
    pool_collections_received = fields.Monetary(
        string='Collections Received', currency_field='currency_id',
        readonly=True, copy=False,
        help='Cash received from DISCOs on this cycle when the pool was snapshotted.',
    )
    pool_previously_advised = fields.Monetary(
        string='Previously Advised', currency_field='currency_id',
        readonly=True, copy=False,
        help='Total of the other payment advices already raised on this cycle '
             '(submitted or beyond) when the pool was snapshotted.',
    )
    pool_available = fields.Monetary(
        string='Available Pool', currency_field='currency_id',
        readonly=True, copy=False,
        help='Collections received minus the amounts already advised.',
    )
    pool_snapshot_date = fields.Datetime(
        string='Pool Snapshot Date', readonly=True, copy=False,
    )

    # ── Totals ─────────────────────────────────────────────────────────────────
    total_outstanding_amount = fields.Monetary(
        compute='_compute_totals', string='Total Outstanding to GENCOs',
        currency_field='currency_id', store=True,
    )
    total_advice_amount = fields.Monetary(
        compute='_compute_totals', string='Total Advised', tracking=True,
        currency_field='currency_id', store=True,
    )
    pool_balance_after = fields.Monetary(
        compute='_compute_totals', string='Pool Balance After',
        currency_field='currency_id',
    )
    line_count = fields.Integer(compute='_compute_totals', string='GENCOs')

    line_ids = fields.One2many(
        'nbet.payment.advice.line', 'advice_id', string='Advice Lines',
        copy=True,
    )

    # ── Approval stamps ────────────────────────────────────────────────────────
    submitted_by_id = fields.Many2one(
        'res.users', string='Prepared By', readonly=True, copy=False,
    )
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)

    ocma_approver_id = fields.Many2one(
        'res.users', string='Head of OCMA', readonly=True, copy=False, tracking=True,
    )
    ocma_approval_date = fields.Datetime(
        string='OCMA Approval Date', readonly=True, copy=False,
    )
    ocma_notes = fields.Text(string='OCMA Notes')

    md_approver_id = fields.Many2one(
        'res.users', string='Managing Director', readonly=True, copy=False, tracking=True,
    )
    md_approval_date = fields.Datetime(
        string='MD Approval Date', readonly=True, copy=False,
    )
    md_notes = fields.Text(string='MD Notes')

    rejection_reason = fields.Text(string='Rejection Reason', copy=False)
    rejected_by_id = fields.Many2one(
        'res.users', string='Rejected By', readonly=True, copy=False,
    )
    rejection_date = fields.Datetime(string='Rejected On', readonly=True, copy=False)

    @api.depends('line_ids.outstanding_amount', 'line_ids.advice_amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_outstanding_amount = sum(rec.line_ids.mapped('outstanding_amount'))
            rec.total_advice_amount = sum(rec.line_ids.mapped('advice_amount'))
            rec.pool_balance_after = rec.pool_available - rec.total_advice_amount
            rec.line_count = len(rec.line_ids)

    # ── Constraints ────────────────────────────────────────────────────────────
    @api.constrains('billing_cycle_id')
    def _check_cycle_posted(self):
        # The pool is measured off posted DISCO invoices and the allocation off
        # posted GENCO vendor bills — neither exists before the cycle is posted.
        for rec in self:
            if rec.billing_cycle_id.state not in ('posted', 'locked'):
                raise ValidationError(
                    'A payment advice can only be raised on a posted or locked '
                    'billing cycle. Cycle "%s" is %s.'
                    % (rec.billing_cycle_id.name, rec.billing_cycle_id.state)
                )

    def _check_pool(self):
        for rec in self:
            if rec.state in ('rejected', 'cancelled'):
                continue
            rounding = rec.currency_id.rounding or 0.01
            total = sum(rec.line_ids.mapped('advice_amount'))
            if float_compare(total, rec.pool_available, precision_rounding=rounding) > 0:
                raise ValidationError(
                    'The total advised on %s (%.2f) exceeds the available '
                    'collections pool (%.2f). Reduce the line amounts or '
                    'recompute the allocation.'
                    % (rec.name, total, rec.pool_available)
                )

    @api.constrains('line_ids', 'pool_available')
    def _check_pool_constrains(self):
        self._check_pool()

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_progress(self):
        for rec in self:
            if rec.state not in ('draft', 'cancelled'):
                raise UserError(
                    'Payment advice %s is %s and cannot be deleted. '
                    'Cancel it first.' % (rec.name, rec.state)
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nbet.payment.advice') or 'New'
        return super().create(vals_list)

    # ── Pool snapshot ──────────────────────────────────────────────────────────
    def _sibling_advices(self, states):
        self.ensure_one()
        return self.search([
            ('billing_cycle_id', '=', self.billing_cycle_id.id),
            ('id', '!=', self.id),
            ('state', 'in', states),
        ])

    def _sibling_reserved_amount(self):
        """Pool already committed to other advices of this cycle.

        Paid advices stay counted: the cash they disbursed left the pool, while
        pool_collections_received keeps growing as new DISCO cash arrives.
        """
        self.ensure_one()
        siblings = self._sibling_advices(
            ['submitted', 'ocma_approved', 'md_approved', 'sent_to_treasury', 'paid'])
        return sum(siblings.mapped('total_advice_amount'))

    def _genco_reserved_amounts(self):
        """{participant_id: amount} committed to each GENCO on in-flight siblings.

        Paid siblings are excluded here — their payment already reduced the
        vendor bills' residual, so counting them again would double-deduct.
        """
        self.ensure_one()
        siblings = self._sibling_advices(
            ['submitted', 'ocma_approved', 'md_approved', 'sent_to_treasury'])
        reserved = {}
        for line in siblings.line_ids:
            reserved[line.participant_id.id] = (
                reserved.get(line.participant_id.id, 0.0) + line.advice_amount
            )
        return reserved

    def _pool_vals(self):
        self.ensure_one()
        received = self.billing_cycle_id.total_payment_received
        advised = self._sibling_reserved_amount()
        return {
            'pool_collections_received': received,
            'pool_previously_advised': advised,
            'pool_available': max(0.0, received - advised),
            'pool_snapshot_date': fields.Datetime.now(),
        }

    def _snapshot_pool(self):
        for rec in self:
            rec.write(rec._pool_vals())

    # ── Allocation ─────────────────────────────────────────────────────────────
    @api.model
    def _allocate_largest_remainder(self, target, outstanding_map, rounding):
        """Split ``target`` across the keys of ``outstanding_map`` pro-rata to
        their outstanding amounts, in whole currency-rounding steps.

        Largest-remainder method: the shares sum exactly to ``target`` and no
        share exceeds its outstanding amount.
        """
        rounding = rounding or 0.01
        total_outstanding = sum(outstanding_map.values())
        if float_compare(total_outstanding, 0.0, precision_rounding=rounding) <= 0:
            return {key: 0.0 for key in outstanding_map}
        if float_compare(target, total_outstanding, precision_rounding=rounding) >= 0:
            return dict(outstanding_map)
        target_steps = int(float_round(target / rounding, precision_digits=0))
        shares, remainders, caps = {}, {}, {}
        for key, outstanding in outstanding_map.items():
            raw = target_steps * (outstanding / total_outstanding)
            shares[key] = int(raw)
            remainders[key] = raw - int(raw)
            caps[key] = int(float_round(outstanding / rounding, precision_digits=0))
        leftover = target_steps - sum(shares.values())
        for key in sorted(outstanding_map,
                          key=lambda k: (-remainders[k], -outstanding_map[k], k)):
            if leftover <= 0:
                break
            if shares[key] >= caps[key]:
                continue
            shares[key] += 1
            leftover -= 1
        return {
            key: float_round(steps * rounding, precision_rounding=rounding)
            for key, steps in shares.items()
        }

    def _get_open_genco_moves(self):
        """{participant: posted vendor bills/refunds of the cycle}, keyed off the
        settlement stamp every generated document carries."""
        self.ensure_one()
        grouped = {}
        for move in self.billing_cycle_id._get_payable_moves():
            participant = move.nbet_participant_id
            if not participant or participant.participant_type != 'genco':
                continue
            grouped.setdefault(participant, self.env['account.move'])
            grouped[participant] |= move
        return grouped

    def action_generate_lines(self):
        """Snapshot the pool and (re)build the lines, one per GENCO with an open
        balance, pre-filled with its pro-rata share of the pool."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(
                    'The allocation of %s can only be recomputed while it is a '
                    'draft.' % rec.name
                )
            # Clear the old lines before the snapshot: a shrunken pool must not
            # trip the pool constraint against lines about to be replaced.
            rec.line_ids = [(5, 0, 0)]
            rec._snapshot_pool()
            rounding = rec.currency_id.rounding or 0.01

            grouped = rec._get_open_genco_moves()
            reserved = rec._genco_reserved_amounts()
            outstanding_map, moves_by_participant = {}, {}
            for participant, moves in grouped.items():
                outstanding = (
                    sum(m._nbet_open_amount() for m in moves)
                    - reserved.get(participant.id, 0.0)
                )
                if float_compare(outstanding, 0.0, precision_rounding=rounding) <= 0:
                    continue
                outstanding_map[participant.id] = outstanding
                moves_by_participant[participant.id] = moves

            target = min(rec.pool_available, sum(outstanding_map.values()))
            shares = rec._allocate_largest_remainder(target, outstanding_map, rounding)

            rec.line_ids = [
                (0, 0, {
                    'participant_id': participant_id,
                    'vendor_bill_ids': [(6, 0, moves_by_participant[participant_id].ids)],
                    'outstanding_amount': outstanding_map[participant_id],
                    'pro_rata_share': shares[participant_id],
                    'advice_amount': shares[participant_id],
                })
                for participant_id in sorted(
                    outstanding_map, key=lambda p: -outstanding_map[p])
            ]
            rec.message_post(
                body='Allocation computed: pool of %.2f shared across %s GENCO(s), '
                     '%.2f suggested in total.'
                     % (rec.pool_available, len(rec.line_ids), rec.total_advice_amount)
            )

    # ── Workflow ───────────────────────────────────────────────────────────────
    def _notify_group(self, group_xmlid, summary, note):
        self.ensure_one()
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return
        for user in group.users:
            if user == self.env.user or not user.active:
                continue
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=summary, note=note, user_id=user.id,
            )

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Only draft advices can be submitted.')
            if not rec.line_ids:
                raise UserError(
                    'Compute the allocation of %s before submitting it.' % rec.name
                )
            rounding = rec.currency_id.rounding or 0.01
            if float_compare(rec.total_advice_amount, 0.0,
                             precision_rounding=rounding) <= 0:
                raise UserError(
                    '%s advises no payment. Set the amounts before submitting.'
                    % rec.name
                )
            # Collections or sibling advices may have moved since the lines were
            # generated — re-check against the pool as it stands right now,
            # before freezing it, so an overdraw fails with this message rather
            # than with the pool constraint.
            pool_vals = rec._pool_vals()
            if float_compare(rec.total_advice_amount, pool_vals['pool_available'],
                             precision_rounding=rounding) > 0:
                raise UserError(
                    'The total advised on %s (%.2f) now exceeds the available '
                    'pool (%.2f) — another advice has claimed part of the '
                    'collections since the allocation was computed. Recompute '
                    'the allocation.'
                    % (rec.name, rec.total_advice_amount,
                       pool_vals['pool_available'])
                )
            rec.write(pool_vals)
            rec.write({
                'state': 'submitted',
                'submitted_by_id': self.env.user.id,
                'submitted_date': fields.Datetime.now(),
                'rejection_reason': False,
                'rejected_by_id': False,
                'rejection_date': False,
            })
            rec.message_post(
                body='Payment advice submitted by %s: %s GENCO(s), %.2f advised '
                     'from a pool of %.2f.'
                     % (self.env.user.display_name, rec.line_count,
                        rec.total_advice_amount, rec.pool_available)
            )
            rec._notify_group(
                'nbet_power_billing.group_nbet_ocma_head',
                'Approve payment advice %s' % rec.name,
                'Payment advice %s for cycle %s advises %.2f to %s GENCO(s) and '
                'awaits your approval.'
                % (rec.name, rec.billing_cycle_id.name,
                   rec.total_advice_amount, rec.line_count),
            )

    def action_ocma_approve(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_ocma_head'):
            raise UserError('Only the Head of OCMA can approve at this stage.')
        for rec in self:
            if rec.state != 'submitted':
                raise UserError('%s is not awaiting OCMA approval.' % rec.name)
            rec.write({
                'state': 'ocma_approved',
                'ocma_approver_id': self.env.user.id,
                'ocma_approval_date': fields.Datetime.now(),
            })
            rec.message_post(
                body='Approved by the Head of OCMA (%s).' % self.env.user.display_name
            )
            rec._notify_group(
                'nbet_power_billing.group_nbet_md',
                'Approve payment advice %s' % rec.name,
                'Payment advice %s (%.2f to %s GENCO(s)) has been approved by '
                'the Head of OCMA and awaits your approval.'
                % (rec.name, rec.total_advice_amount, rec.line_count),
            )

    def action_md_approve(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_md'):
            raise UserError('Only the Managing Director can approve at this stage.')
        for rec in self:
            if rec.state != 'ocma_approved':
                raise UserError('%s is not awaiting MD approval.' % rec.name)
            if rec.ocma_approver_id == self.env.user:
                raise UserError(
                    'Segregation of duties: the MD approval must be performed '
                    'by a different person than the Head of OCMA.'
                )
            rec.write({
                'state': 'md_approved',
                'md_approver_id': self.env.user.id,
                'md_approval_date': fields.Datetime.now(),
            })
            rec.message_post(
                body='Approved by the Managing Director (%s).'
                     % self.env.user.display_name
            )
            rec._notify_group(
                'nbet_power_billing.group_nbet_settlement_manager',
                'Send payment advice %s to Treasury' % rec.name,
                'Payment advice %s has full approval and is ready to be sent '
                'to Treasury for payment.' % rec.name,
            )

    def action_reject(self):
        if not (self.env.user.has_group('nbet_power_billing.group_nbet_ocma_head')
                or self.env.user.has_group('nbet_power_billing.group_nbet_md')):
            raise UserError(
                'Only the Head of OCMA or the Managing Director can reject a '
                'payment advice.'
            )
        for rec in self:
            if rec.state not in ('submitted', 'ocma_approved'):
                raise UserError('%s is not in the approval chain.' % rec.name)
            if not rec.rejection_reason:
                raise UserError(
                    'Enter the rejection reason on %s before rejecting it.' % rec.name
                )
            rec.write({
                'state': 'rejected',
                'rejected_by_id': self.env.user.id,
                'rejection_date': fields.Datetime.now(),
                'ocma_approver_id': False,
                'ocma_approval_date': False,
            })
            rec.message_post(
                body='Payment advice rejected by %s: %s'
                     % (self.env.user.display_name, rec.rejection_reason)
            )
            if rec.submitted_by_id and rec.submitted_by_id != self.env.user:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary='Payment advice %s rejected' % rec.name,
                    note='Rejected by %s: %s' % (self.env.user.display_name,
                                                 rec.rejection_reason),
                    user_id=rec.submitted_by_id.id,
                )

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != 'rejected':
                raise UserError(
                    'Only a rejected advice can be reset to draft. %s is %s.'
                    % (rec.name, rec.state)
                )
            rec.write({
                'state': 'draft',
                'submitted_by_id': False,
                'submitted_date': False,
                'ocma_approver_id': False,
                'ocma_approval_date': False,
                'md_approver_id': False,
                'md_approval_date': False,
            })
            rec.message_post(body='Payment advice reset to draft.')

    def action_cancel(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_settlement_manager'):
            raise UserError('Only Settlement Managers can cancel a payment advice.')
        for rec in self:
            if rec.state in ('sent_to_treasury', 'paid'):
                raise UserError(
                    '%s is already with Treasury. Cancel the payment schedule '
                    'there first.' % rec.name
                )
            if rec.state == 'cancelled':
                continue
            rec.write({'state': 'cancelled'})
            rec.message_post(
                body='Payment advice cancelled by %s.' % self.env.user.display_name
            )

    def action_print_advice(self):
        return self.env.ref(
            'nbet_power_billing.action_report_payment_advice').report_action(self)


class NbetPaymentAdviceLine(models.Model):
    _name = 'nbet.payment.advice.line'
    _description = 'NBET GENCO Payment Advice Line'
    _order = 'advice_id, outstanding_amount desc, id'

    advice_id = fields.Many2one(
        'nbet.payment.advice', string='Payment Advice', required=True,
        ondelete='cascade', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='GENCO', required=True,
        ondelete='restrict', domain=[('participant_type', '=', 'genco')],
    )
    partner_id = fields.Many2one(
        'res.partner', related='participant_id.partner_id', store=True,
        string='Payee',
    )
    currency_id = fields.Many2one(related='advice_id.currency_id')
    state = fields.Selection(related='advice_id.state', store=True)
    vendor_bill_ids = fields.Many2many(
        'account.move', 'nbet_payment_advice_line_move_rel',
        'line_id', 'move_id', string='Vendor Bills', readonly=True,
        help='Posted cycle vendor bills the outstanding balance was measured on.',
    )
    outstanding_amount = fields.Monetary(
        string='Outstanding', currency_field='currency_id', readonly=True,
        help='Open balance on the GENCO\'s posted cycle vendor bills when the '
             'allocation was computed, net of amounts on other in-flight advices.',
    )
    pro_rata_share = fields.Monetary(
        string='Pro-rata Share', currency_field='currency_id', readonly=True,
        help='The suggested amount: the GENCO\'s share of the pool, pro-rata '
             'to its outstanding balance.',
    )
    advice_amount = fields.Monetary(
        string='Amount to Pay', currency_field='currency_id', required=True,
        default=0.0,
        help='The amount the committee decided to pay this GENCO.',
    )
    remarks = fields.Char(string='Remarks')

    _sql_constraints = [
        ('advice_participant_uniq', 'unique(advice_id, participant_id)',
         'A GENCO can appear only once per payment advice.'),
    ]

    @api.constrains('advice_amount', 'outstanding_amount')
    def _check_amounts(self):
        for line in self:
            if line.advice_id.state in ('rejected', 'cancelled'):
                continue
            rounding = line.currency_id.rounding or 0.01
            if float_compare(line.advice_amount, 0.0,
                             precision_rounding=rounding) < 0:
                raise ValidationError(
                    'The amount to pay %s cannot be negative.'
                    % line.participant_id.display_name
                )
            if float_compare(line.advice_amount, line.outstanding_amount,
                             precision_rounding=rounding) > 0:
                raise ValidationError(
                    'The amount to pay %s (%.2f) exceeds its outstanding '
                    'balance (%.2f).'
                    % (line.participant_id.display_name,
                       line.advice_amount, line.outstanding_amount)
                )
        self.mapped('advice_id')._check_pool()
