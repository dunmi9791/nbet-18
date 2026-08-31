# -*- coding: utf-8 -*-
"""
NBET Meristem DISCO Collection Advice
Meristem (the collections agent) periodically advises NBET of the payments it
has received from each DISCO on a posted billing cycle. Finance captures the
advice, then verifies each advised amount in one or more confirmation entries:
in the bank, still with Remita (the payment gateway), or not seen at all.

Amounts confirmed in the bank become posted inbound customer payments,
reconciled against the DISCO's posted cycle invoices oldest-first, which feeds
the cycle's collections pool. "With Remita" and "not seen" entries carry no
accounting — they record what finance found, and are cancelled and re-entered
as in-bank once the money lands.

State machine (advice): draft → confirmed → done, any → cancelled while no
confirmation is posted. Confirmation entries: draft → posted → (cancelled for
the tracking statuses only — a posted in-bank entry is undone by reversing its
payment in accounting).
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare
from odoo.tools.misc import formatLang


class NbetCollectionAdvice(models.Model):
    _name = 'nbet.collection.advice'
    _description = 'NBET DISCO Collection Advice (Meristem)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ── Identity ───────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Advice Number', required=True, readonly=True,
        default='New', copy=False, index=True,
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
    meristem_reference = fields.Char(
        string='Meristem Reference', tracking=True,
        help='Reference of the advice document received from Meristem.',
    )
    notes = fields.Text(string='Notes')

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('done', 'Fully Verified'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft', required=True, tracking=True, index=True, copy=False,
    )

    line_ids = fields.One2many(
        'nbet.collection.advice.line', 'advice_id', string='Advice Lines',
        copy=True,
    )
    confirmation_ids = fields.One2many(
        'nbet.collection.confirmation', 'advice_id', string='Confirmations',
    )

    # ── Totals ─────────────────────────────────────────────────────────────────
    total_advised = fields.Monetary(
        compute='_compute_totals', string='Total Advised', store=True,
        currency_field='currency_id', tracking=True,
    )
    total_in_bank = fields.Monetary(
        compute='_compute_totals', string='Confirmed in Bank',
        currency_field='currency_id',
    )
    total_with_remita = fields.Monetary(
        compute='_compute_totals', string='With Remita',
        currency_field='currency_id',
    )
    total_not_seen = fields.Monetary(
        compute='_compute_totals', string='Not Seen',
        currency_field='currency_id',
    )
    total_pending = fields.Monetary(
        compute='_compute_totals', string='Pending Verification',
        currency_field='currency_id',
    )
    line_count = fields.Integer(compute='_compute_totals', string='DISCOs')

    @api.depends('line_ids.amount_advised', 'line_ids.amount_in_bank',
                 'line_ids.amount_with_remita', 'line_ids.amount_not_seen',
                 'line_ids.amount_pending')
    def _compute_totals(self):
        for rec in self:
            rec.total_advised = sum(rec.line_ids.mapped('amount_advised'))
            rec.total_in_bank = sum(rec.line_ids.mapped('amount_in_bank'))
            rec.total_with_remita = sum(rec.line_ids.mapped('amount_with_remita'))
            rec.total_not_seen = sum(rec.line_ids.mapped('amount_not_seen'))
            rec.total_pending = sum(rec.line_ids.mapped('amount_pending'))
            rec.line_count = len(rec.line_ids)

    # ── Constraints ────────────────────────────────────────────────────────────
    @api.constrains('billing_cycle_id')
    def _check_cycle_posted(self):
        # Bank confirmations reconcile against posted DISCO invoices, which do
        # not exist before the cycle is posted.
        for rec in self:
            if rec.billing_cycle_id.state not in ('posted', 'locked'):
                raise ValidationError(
                    'A collection advice can only be raised on a posted or '
                    'locked billing cycle. Cycle "%s" is %s.'
                    % (rec.billing_cycle_id.name, rec.billing_cycle_id.state)
                )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_progress(self):
        for rec in self:
            if rec.state not in ('draft', 'cancelled'):
                raise UserError(
                    'Collection advice %s is %s and cannot be deleted. '
                    'Cancel it first.' % (rec.name, rec.state)
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nbet.collection.advice') or 'New'
        return super().create(vals_list)

    def _posted_confirmations(self):
        return self.confirmation_ids.filtered(lambda c: c.state == 'posted')

    # ── Workflow ───────────────────────────────────────────────────────────────
    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Only draft advices can be confirmed.')
            if not rec.line_ids:
                raise UserError(
                    'Add the advised DISCO amounts to %s before confirming it.'
                    % rec.name
                )
            rounding = rec.currency_id.rounding or 0.01
            if float_compare(rec.total_advised, 0.0,
                             precision_rounding=rounding) <= 0:
                raise UserError(
                    '%s advises no collection. Set the amounts before '
                    'confirming it.' % rec.name
                )
            rec.write({'state': 'confirmed'})
            rec.message_post(
                body='Collection advice confirmed by %s: %s DISCO(s), %.2f '
                     'advised on cycle %s. Verification is now open.'
                     % (self.env.user.display_name, rec.line_count,
                        rec.total_advised, rec.billing_cycle_id.name)
            )

    def action_cancel(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            if rec._posted_confirmations():
                raise UserError(
                    '%s has posted confirmations and cannot be cancelled. '
                    'Cancel the confirmations first (in-bank ones by reversing '
                    'their payments in accounting).' % rec.name
                )
            rec.write({'state': 'cancelled'})
            rec.message_post(
                body='Collection advice cancelled by %s.'
                     % self.env.user.display_name
            )

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('confirmed', 'cancelled'):
                raise UserError(
                    'Only a confirmed or cancelled advice can be reset to '
                    'draft. %s is %s.' % (rec.name, rec.state)
                )
            if rec._posted_confirmations():
                raise UserError(
                    '%s has posted confirmations and can no longer be reset '
                    'to draft.' % rec.name
                )
            rec.write({'state': 'draft'})
            rec.message_post(body='Collection advice reset to draft.')

    def _sync_done_state(self):
        """Flip confirmed ⇄ done as the lines become (un)fully verified."""
        for rec in self:
            if rec.state not in ('confirmed', 'done'):
                continue
            fully_verified = rec.line_ids and all(
                line.verification_status == 'full' for line in rec.line_ids
            )
            target = 'done' if fully_verified else 'confirmed'
            if rec.state != target:
                rec.write({'state': target})
                if target == 'done':
                    rec.message_post(
                        body='Every advised amount has been verified: %.2f in '
                             'bank, %.2f with Remita, %.2f not seen.'
                             % (rec.total_in_bank, rec.total_with_remita,
                                rec.total_not_seen)
                    )


class NbetCollectionAdviceLine(models.Model):
    _name = 'nbet.collection.advice.line'
    _description = 'NBET DISCO Collection Advice Line'
    _order = 'advice_id, amount_advised desc, id'
    # Confirmations pick their advice line from a dropdown: label the lines by
    # DISCO (and let name_search match on it) rather than the "model,id" default.
    _rec_name = 'participant_id'

    @api.depends('participant_id.display_name', 'amount_advised')
    def _compute_display_name(self):
        for line in self:
            line.display_name = '%s (%s advised)' % (
                line.participant_id.display_name,
                formatLang(self.env, line.amount_advised,
                           currency_obj=line.currency_id),
            )

    advice_id = fields.Many2one(
        'nbet.collection.advice', string='Collection Advice', required=True,
        ondelete='cascade', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='DISCO', required=True,
        ondelete='restrict', domain=[('participant_type', '=', 'disco')],
    )
    partner_id = fields.Many2one(
        'res.partner', related='participant_id.partner_id', store=True,
        string='Payer',
    )
    currency_id = fields.Many2one(related='advice_id.currency_id')
    company_id = fields.Many2one(related='advice_id.company_id')
    state = fields.Selection(related='advice_id.state', store=True)
    amount_advised = fields.Monetary(
        string='Amount Advised', currency_field='currency_id', required=True,
        default=0.0,
        help='The amount Meristem advises was received from this DISCO.',
    )
    confirmation_ids = fields.One2many(
        'nbet.collection.confirmation', 'line_id', string='Confirmations',
    )
    amount_in_bank = fields.Monetary(
        compute='_compute_amounts', string='In Bank',
        currency_field='currency_id',
    )
    amount_with_remita = fields.Monetary(
        compute='_compute_amounts', string='With Remita',
        currency_field='currency_id',
    )
    amount_not_seen = fields.Monetary(
        compute='_compute_amounts', string='Not Seen',
        currency_field='currency_id',
    )
    amount_pending = fields.Monetary(
        compute='_compute_amounts', string='Pending Verification',
        currency_field='currency_id',
        help='The part of the advised amount finance has not verified yet.',
    )
    verification_status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('partial', 'Partially Verified'),
            ('full', 'Fully Verified'),
        ],
        compute='_compute_amounts', string='Verification',
    )
    remarks = fields.Char(string='Remarks')

    _sql_constraints = [
        ('advice_participant_uniq', 'unique(advice_id, participant_id)',
         'A DISCO can appear only once per collection advice.'),
    ]

    @api.depends('amount_advised', 'confirmation_ids.state',
                 'confirmation_ids.status', 'confirmation_ids.amount')
    def _compute_amounts(self):
        for line in self:
            posted = line.confirmation_ids.filtered(
                lambda c: c.state == 'posted')
            by_status = {
                status: sum(
                    posted.filtered(lambda c: c.status == status)
                    .mapped('amount'))
                for status in ('in_bank', 'with_remita', 'not_seen')
            }
            line.amount_in_bank = by_status['in_bank']
            line.amount_with_remita = by_status['with_remita']
            line.amount_not_seen = by_status['not_seen']
            verified = sum(by_status.values())
            line.amount_pending = line.amount_advised - verified
            rounding = line.currency_id.rounding or 0.01
            if float_compare(line.amount_pending, 0.0,
                             precision_rounding=rounding) <= 0 and posted:
                line.verification_status = 'full'
            elif posted:
                line.verification_status = 'partial'
            else:
                line.verification_status = 'pending'

    @api.constrains('amount_advised')
    def _check_amount_advised(self):
        for line in self:
            if line.advice_id.state == 'cancelled':
                continue
            rounding = line.currency_id.rounding or 0.01
            if float_compare(line.amount_advised, 0.0,
                             precision_rounding=rounding) <= 0:
                raise ValidationError(
                    'The amount advised for %s must be greater than zero.'
                    % line.participant_id.display_name
                )
            line._check_not_overconfirmed()

    def _check_not_overconfirmed(self):
        for line in self:
            if line.advice_id.state == 'cancelled':
                continue
            rounding = line.currency_id.rounding or 0.01
            verified = sum(
                line.confirmation_ids
                .filtered(lambda c: c.state == 'posted').mapped('amount'))
            if float_compare(verified, line.amount_advised,
                             precision_rounding=rounding) > 0:
                raise ValidationError(
                    'The posted confirmations for %s (%.2f) exceed the amount '
                    'advised (%.2f) on %s.'
                    % (line.participant_id.display_name, verified,
                       line.amount_advised, line.advice_id.name)
                )


class NbetCollectionConfirmation(models.Model):
    _name = 'nbet.collection.confirmation'
    _description = 'NBET DISCO Collection Confirmation'
    _order = 'confirmation_date desc, id desc'

    name = fields.Char(
        string='Confirmation Number', required=True, readonly=True,
        default='New', copy=False, index=True,
    )
    line_id = fields.Many2one(
        'nbet.collection.advice.line', string='Advice Line', required=True,
        ondelete='cascade', index=True,
    )
    advice_id = fields.Many2one(
        related='line_id.advice_id', string='Collection Advice',
        store=True, index=True,
    )
    participant_id = fields.Many2one(
        related='line_id.participant_id', string='DISCO', store=True,
    )
    partner_id = fields.Many2one(
        related='line_id.partner_id', string='Payer',
    )
    billing_cycle_id = fields.Many2one(
        related='advice_id.billing_cycle_id', string='Billing Cycle',
        store=True,
    )
    currency_id = fields.Many2one(related='advice_id.currency_id')
    company_id = fields.Many2one(related='advice_id.company_id')
    amount_advised = fields.Monetary(
        related='line_id.amount_advised', string='Amount Advised',
    )
    amount_pending = fields.Monetary(
        related='line_id.amount_pending', string='Pending on Line',
    )

    status = fields.Selection(
        selection=[
            ('in_bank', 'In Bank'),
            ('with_remita', 'With Remita'),
            ('not_seen', 'Not Seen'),
        ],
        string='Verification Result', required=True,
        help='What finance found for this part of the advised amount: the '
             'money is in the bank, still with Remita, or nowhere to be seen.',
    )
    amount = fields.Monetary(
        string='Amount', currency_field='currency_id', required=True,
    )
    confirmation_date = fields.Date(
        string='Confirmation Date', required=True,
        default=fields.Date.context_today,
    )
    journal_id = fields.Many2one(
        'account.journal', string='Bank Journal',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        help='Bank journal the funds landed in. Required for in-bank '
             'confirmations.',
    )
    payment_reference = fields.Char(
        string='Payment Reference', copy=False,
        help='Bank credit reference for the in-bank confirmation.',
    )
    remita_reference = fields.Char(
        string='Remita Reference (RRR)',
        help='Remita retrieval reference of the transaction, for amounts '
             'still with Remita.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('posted', 'Posted'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft', required=True, copy=False, index=True,
    )
    payment_id = fields.Many2one(
        'account.payment', string='Odoo Payment', readonly=True, copy=False,
    )
    note = fields.Char(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nbet.collection.confirmation') or 'New'
        return super().create(vals_list)

    @api.constrains('amount', 'state', 'status')
    def _check_amounts(self):
        for rec in self:
            rounding = rec.currency_id.rounding or 0.01
            if float_compare(rec.amount, 0.0,
                             precision_rounding=rounding) <= 0:
                raise ValidationError(
                    'The amount on confirmation %s must be greater than zero.'
                    % rec.name
                )
        self.mapped('line_id')._check_not_overconfirmed()

    # ── Accounting ─────────────────────────────────────────────────────────────
    def _get_open_cycle_invoices(self):
        """The DISCO's posted cycle invoices with an open balance, oldest
        first — the order the payment is drawn down in."""
        self.ensure_one()
        return self.billing_cycle_id._get_receivable_moves().filtered(
            lambda m: m.nbet_participant_id == self.participant_id
            and m.amount_residual
        ).sorted(lambda m: (m.invoice_date or m.date, m.id))

    def _prepare_payment_vals(self):
        self.ensure_one()
        return {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'journal_id': self.journal_id.id,
            'date': self.confirmation_date,
            'memo': '%s / %s / %s' % (
                self.name, self.advice_id.name, self.billing_cycle_id.code),
            'payment_reference': self.payment_reference,
        }

    def _create_account_payment(self):
        self.ensure_one()
        payment = self.env['account.payment'].sudo().create(
            self._prepare_payment_vals())
        payment.action_post()
        self._reconcile_against_invoices(payment)
        return payment

    def _reconcile_against_invoices(self, payment):
        """Draw the payment down against the DISCO's posted cycle invoices.

        Raises rather than skipping: an unreconciled confirmation would show
        the cycle as collected while the receivable still stands open in the
        ledger, which is the one thing this workflow exists to prevent.
        """
        self.ensure_one()
        invoices = self._get_open_cycle_invoices()
        receivable = lambda line: (
            line.account_id.account_type == 'asset_receivable'
            and line.partner_id == self.partner_id
            and not line.reconciled
        )
        payment_lines = payment.move_id.line_ids.sudo().filtered(receivable)
        if not payment_lines:
            raise UserError(
                'The payment posted for %s has no open receivable line to '
                'reconcile. Check the configuration of journal %s.'
                % (self.name, self.journal_id.display_name)
            )
        invoice_lines = invoices.line_ids.sudo().filtered(receivable)
        if not invoice_lines:
            raise UserError(
                '%s has no open posted invoice for %s on cycle %s to '
                'reconcile %s against. Check whether the invoices were '
                'settled outside this workflow.'
                % (self.billing_cycle_id.name,
                   self.participant_id.display_name,
                   self.billing_cycle_id.code, self.name)
            )
        (invoice_lines + payment_lines).reconcile()
        rounding = self.currency_id.rounding or 0.01
        # Whatever the payment could not settle stays as credit on the
        # DISCO's account — worth a note, not an error.
        unmatched = sum(
            line.amount_residual for line in payment_lines if not line.reconciled
        )
        if float_compare(abs(unmatched), 0.0, precision_rounding=rounding) > 0:
            self.advice_id.message_post(
                body='Confirmation %s: %.2f of the %.2f received from %s '
                     'exceeds the open cycle invoices and stays as credit on '
                     'the partner account.'
                     % (self.name, abs(unmatched), self.amount,
                        self.participant_id.display_name)
            )

    def _check_postable(self):
        self.ensure_one()
        if self.advice_id.state not in ('confirmed', 'done'):
            raise UserError(
                '%s can only be posted on a confirmed advice. %s is %s.'
                % (self.name, self.advice_id.name, self.advice_id.state)
            )
        rounding = self.currency_id.rounding or 0.01
        if float_compare(self.amount, 0.0, precision_rounding=rounding) <= 0:
            raise UserError(
                'The amount on %s must be greater than zero.' % self.name
            )
        if float_compare(self.amount, self.line_id.amount_pending,
                         precision_rounding=rounding) > 0:
            raise UserError(
                '%s verifies %.2f but only %.2f of the amount advised for %s '
                'is still unverified. A confirmation cannot exceed the '
                'advised amount.'
                % (self.name, self.amount, self.line_id.amount_pending,
                   self.participant_id.display_name)
            )
        if self.status != 'in_bank':
            return
        if not self.partner_id:
            raise UserError(
                'DISCO %s has no Odoo contact, so no payment can be recorded '
                'for %s. Link a partner on the market participant first.'
                % (self.participant_id.display_name, self.name)
            )
        if not self.journal_id:
            raise UserError(
                'Select the bank journal the funds landed in on %s before '
                'posting it.' % self.name
            )
        if not self.payment_reference:
            raise UserError(
                'Enter the bank payment reference on %s before posting it.'
                % self.name
            )
        if not self._get_open_cycle_invoices():
            raise UserError(
                'There is no open posted invoice for %s on cycle %s to '
                'reconcile %s against.'
                % (self.participant_id.display_name,
                   self.billing_cycle_id.name, self.name)
            )

    # ── Actions ────────────────────────────────────────────────────────────────
    def action_post(self):
        if not self.env.user.has_group(
                'nbet_power_billing.group_nbet_accounting_officer'):
            raise UserError(
                'Only Accounting Officers can post collection confirmations.'
            )
        status_labels = dict(self._fields['status'].selection)
        for rec in self:
            if rec.state != 'draft':
                raise UserError('%s has already been posted.' % rec.name)
            rec._check_postable()
            if rec.status == 'in_bank':
                rec.payment_id = rec._create_account_payment()
            rec.state = 'posted'
            body = (
                'Confirmation %s posted by %s: %.2f from %s verified as '
                '"%s" on %s.'
                % (rec.name, self.env.user.display_name, rec.amount,
                   rec.participant_id.display_name,
                   status_labels[rec.status], rec.confirmation_date)
            )
            if rec.payment_id:
                body += ' Odoo payment %s posted into %s, reference %s.' % (
                    rec.payment_id.name, rec.journal_id.display_name,
                    rec.payment_reference)
            rec.advice_id.message_post(body=body)
        self.mapped('advice_id')._sync_done_state()

    def action_cancel(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            if rec.state == 'posted' and rec.status == 'in_bank':
                raise UserError(
                    'Confirmation %s created payment %s and can no longer be '
                    'cancelled. Reverse the payment in accounting instead.'
                    % (rec.name, rec.payment_id.name or '')
                )
            was_posted = rec.state == 'posted'
            rec.state = 'cancelled'
            if was_posted:
                rec.advice_id.message_post(
                    body='Confirmation %s (%.2f, %s) cancelled by %s.'
                         % (rec.name, rec.amount, rec.status,
                            self.env.user.display_name)
                )
        self.mapped('advice_id')._sync_done_state()

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(
                    'Only a cancelled confirmation can be reset to draft.'
                )
            rec.state = 'draft'

    def action_view_payment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'res_id': self.payment_id.id,
            'view_mode': 'form',
        }
