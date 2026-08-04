# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class NisoReceipt(models.Model):
    _name = 'nbet.niso.receipt'
    _description = 'NISO Admin Charge Receipt'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'receipt_date desc, id desc'

    name = fields.Char(
        string='Receipt Number',
        required=True,
        readonly=True,
        default='New',
        copy=False,
        index=True,
    )
    advice_id = fields.Many2one(
        'nbet.niso.advice',
        string='Advice',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
        domain="[('state', 'in', ('confirmed', 'partial'))]",
        help='The advice this receipt is drawn down from.',
    )
    partner_id = fields.Many2one(
        related='advice_id.partner_id',
        string='Received From',
        store=True,
    )
    period_name = fields.Char(
        related='advice_id.period_name',
        string='Period',
        store=True,
    )
    advice_outstanding = fields.Monetary(
        related='advice_id.amount_outstanding',
        string='Advice Outstanding',
        help='What is still owed on the advice before this receipt is posted.',
    )

    receipt_date = fields.Date(
        string='Receipt Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    amount = fields.Monetary(
        string='Amount Received',
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        related='advice_id.currency_id',
        store=True,
    )
    company_id = fields.Many2one(
        related='advice_id.company_id',
        store=True,
        index=True,
    )

    journal_id = fields.Many2one(
        'account.journal',
        string='Receiving Journal',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        tracking=True,
        help='Bank or cash journal the funds landed in.',
    )
    payment_reference = fields.Char(
        string='Payment Reference',
        copy=False,
        tracking=True,
        help='Bank credit reference or teller number for the receipt.',
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)

    payment_id = fields.Many2one(
        'account.payment',
        string='Odoo Payment',
        readonly=True,
        copy=False,
    )
    note = fields.Text(string='Notes')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'The receipt number must be unique.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.niso.receipt') or 'New'
        return super().create(vals_list)

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if float_compare(rec.amount, 0.0, precision_rounding=rec.currency_id.rounding or 0.01) <= 0:
                raise ValidationError(
                    "The amount on receipt %s must be greater than zero." % rec.name
                )

    # ------------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------------
    def _prepare_payment_vals(self):
        self.ensure_one()
        return {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'journal_id': self.journal_id.id,
            'date': self.receipt_date,
            'memo': '%s / %s' % (self.name, self.advice_id.name),
            'payment_reference': self.payment_reference,
        }

    def _create_account_payment(self):
        self.ensure_one()
        payment = self.env['account.payment'].sudo().create(self._prepare_payment_vals())
        payment.action_post()
        self._reconcile_with_invoice(payment)
        return payment

    def _reconcile_with_invoice(self, payment):
        """Draw the receipt down against the advice's receivable invoice.

        Raises rather than skipping: an unreconciled receipt would leave the
        advice showing as drawn down while the receivable still stands open in
        the ledger, which is the one thing this module exists to prevent.
        """
        self.ensure_one()
        invoice = self.advice_id.move_id
        if not invoice or invoice.state != 'posted':
            raise UserError(
                "%s has no posted receivable invoice, so %s cannot be drawn down "
                "against it. Confirm the advice first."
                % (self.advice_id.name, self.name)
            )
        receivable = lambda line: (
            line.account_id.account_type == 'asset_receivable' and not line.reconciled
        )
        invoice_lines = invoice.line_ids.sudo().filtered(receivable)
        payment_lines = payment.move_id.line_ids.sudo().filtered(receivable)
        if not invoice_lines:
            raise UserError(
                "The receivable on %s (invoice %s) is already fully settled in "
                "accounting, so %s cannot be drawn down against it. Check whether the "
                "invoice was paid outside this module."
                % (self.advice_id.name, invoice.name, self.name)
            )
        if not payment_lines:
            raise UserError(
                "The payment posted for %s has no open receivable line to reconcile. "
                "Check the configuration of journal %s."
                % (self.name, self.journal_id.display_name)
            )
        (invoice_lines + payment_lines).reconcile()

    def _check_postable(self):
        self.ensure_one()
        advice = self.advice_id
        if advice.state not in ('confirmed', 'partial'):
            raise UserError(
                "%s can only be posted against an advice whose receivable is open. "
                "%s is %s."
                % (self.name, advice.name,
                   dict(advice._fields['state'].selection)[advice.state].lower())
            )
        rounding = self.currency_id.rounding or 0.01
        if float_compare(self.amount, advice.amount_outstanding, precision_rounding=rounding) > 0:
            raise UserError(
                "%s receives %s but only %s is still outstanding on %s (%s). A receipt "
                "cannot draw down more than the advice owes."
                % (self.name,
                   self.currency_id.format(self.amount),
                   self.currency_id.format(advice.amount_outstanding),
                   advice.name, advice.period_name)
            )
        if not self.journal_id:
            raise UserError(
                "Select the journal the funds were received into on %s before posting it."
                % self.name
            )
        if not self.payment_reference:
            raise UserError(
                "Enter the payment reference on %s before posting it." % self.name
            )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_post(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("%s has already been posted." % rec.name)
            rec._check_postable()
            rec.payment_id = rec._create_account_payment()
            rec.state = 'posted'
            rec.advice_id._sync_receipt_state()
            rec.message_post(
                body="Receipt posted by %s. %s received into %s, reference %s, "
                     "Odoo payment %s. Outstanding on %s is now %s."
                     % (self.env.user.display_name,
                        rec.currency_id.format(rec.amount),
                        rec.journal_id.display_name,
                        rec.payment_reference,
                        rec.payment_id.name,
                        rec.advice_id.name,
                        rec.currency_id.format(rec.advice_id.amount_outstanding))
            )
            rec.advice_id.message_post(
                body="Receipt %s of %s drawn down. %s outstanding on the %s advice."
                     % (rec.name,
                        rec.currency_id.format(rec.amount),
                        rec.currency_id.format(rec.advice_id.amount_outstanding),
                        rec.advice_id.period_name)
            )

    def action_cancel(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(
                    "Receipt %s has been posted and can no longer be cancelled. Reverse "
                    "its payment %s in accounting instead."
                    % (rec.name, rec.payment_id.name or '')
                )
            rec.state = 'cancelled'

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(
                    "Only a cancelled receipt can be reset to draft."
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
