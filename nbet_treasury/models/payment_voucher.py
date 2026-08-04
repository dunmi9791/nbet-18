# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools import consteq, hmac


class PaymentVoucher(models.Model):
    _name = 'nbet.payment.voucher'
    _description = 'Payment Voucher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc, id desc'

    name = fields.Char(
        string='Voucher Number',
        required=True,
        readonly=True,
        default='New',
        copy=False,
        index=True,
    )
    schedule_id = fields.Many2one(
        'nbet.payment.schedule',
        string='Payment Schedule',
        required=True,
        readonly=True,
        ondelete='cascade',
        index=True,
    )
    transaction_reference = fields.Char(
        related='schedule_id.transaction_reference',
        store=True,
        string='Transaction Reference',
    )
    payment_request_id = fields.Many2one(
        related='schedule_id.payment_request_id',
        store=True,
        string='Payment Request',
    )
    contract_award_id = fields.Many2one(
        related='schedule_id.contract_award_id',
        store=True,
        string='Contract Award',
    )

    voucher_type = fields.Selection([
        ('vendor', 'Vendor Payment'),
        ('tax', 'Tax Remittance'),
    ], required=True, readonly=True, tracking=True)
    tax_line_id = fields.Many2one(
        'nbet.payment.schedule.tax',
        string='Deduction Line',
        readonly=True,
        ondelete='set null',
    )

    # --- Payee (vendor details / tax body details) ---
    partner_id = fields.Many2one(
        'res.partner',
        string='Payee',
        required=True,
        readonly=True,
        tracking=True,
    )
    partner_vat = fields.Char(related='partner_id.vat', string='Payee TIN/VAT No.')
    partner_phone = fields.Char(related='partner_id.phone', string='Payee Phone')
    partner_email = fields.Char(related='partner_id.email', string='Payee Email')
    bank_account = fields.Char(string='Beneficiary Bank Account', readonly=True)

    description = fields.Char(readonly=True)
    amount = fields.Float(string='Amount (NGN)', readonly=True, tracking=True)
    currency_id = fields.Many2one(related='schedule_id.currency_id', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted to Audit'),
        ('reviewed', 'Audit Reviewed'),
        ('audited', 'Audited'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True)

    # --- Payment ---
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        domain="[('type', 'in', ('bank', 'cash'))]",
        tracking=True,
        help='Bank or cash journal the disbursement is made from.',
    )
    payment_reference = fields.Char(string='Payment Reference', copy=False, tracking=True)
    payment_date = fields.Date(string='Payment Date', copy=False, tracking=True)
    payment_id = fields.Many2one(
        'account.payment',
        string='Odoo Payment',
        readonly=True,
        copy=False,
    )
    invoice_id = fields.Many2one(
        related='payment_request_id.invoice_id',
        string='Vendor Bill',
    )

    generated_by_id = fields.Many2one('res.users', string='Prepared By', readonly=True)
    generated_on = fields.Datetime(string='Prepared On', readonly=True)

    approval_line_ids = fields.One2many(
        'nbet.payment.voucher.approval',
        'voucher_id',
        string='Approval History',
        readonly=True,
    )
    auth_code = fields.Char(
        string='Voucher Authentication Code',
        readonly=True,
        copy=False,
        help='HMAC fingerprint of the voucher content, used to detect tampering.',
    )
    auth_valid = fields.Boolean(
        string='Authentication Valid',
        compute='_compute_auth_valid',
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'The voucher number must be unique.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.payment.voucher') or 'New'
        vouchers = super().create(vals_list)
        for voucher in vouchers:
            voucher.sudo().auth_code = voucher._build_auth_code()
        return vouchers

    def _auth_payload(self):
        """Content fingerprinted by the voucher authentication code."""
        self.ensure_one()
        return '|'.join([
            self.name or '',
            self.transaction_reference or '',
            str(self.schedule_id.id),
            self.voucher_type or '',
            str(self.partner_id.id),
            '%.2f' % (self.amount or 0.0),
        ])

    def _build_auth_code(self):
        self.ensure_one()
        return hmac(
            self.env(su=True), 'nbet-payment-voucher', self._auth_payload()
        )[:32].upper()

    @api.depends('name', 'transaction_reference', 'voucher_type', 'partner_id', 'amount', 'auth_code')
    def _compute_auth_valid(self):
        for rec in self:
            rec.auth_valid = bool(rec.auth_code) and consteq(rec.auth_code, rec._build_auth_code())

    def _log_approval(self, stage, user, timestamp, notes=False):
        """Append a tamper-evident entry to the voucher's approval history."""
        self.ensure_one()
        return self.env['nbet.payment.voucher.approval'].create({
            'voucher_id': self.id,
            'sequence': len(self.approval_line_ids) * 10 + 10,
            'stage': stage,
            'user_id': user.id if user else False,
            'user_login': user.login if user else '',
            'approval_datetime': timestamp,
            'notes': notes or False,
        })

    # ------------------------------------------------------------------
    # Payment
    # ------------------------------------------------------------------
    def _prepare_payment_vals(self):
        self.ensure_one()
        vals = {
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'journal_id': self.payment_journal_id.id,
            'date': self.payment_date,
            'memo': '%s%s' % (
                self.name,
                ' / %s' % self.transaction_reference if self.transaction_reference else '',
            ),
            'payment_reference': self.payment_reference,
        }
        if self.voucher_type == 'tax':
            # Remitting clears the liability raised when the vendor was paid,
            # so the payment lands on the tax payable account rather than on AP.
            account = self.tax_line_id.tax_payable_account_id
            if not account:
                raise UserError(
                    "Set a Tax Payable Account on the deduction '%s' of %s before "
                    "paying its remittance voucher."
                    % (self.tax_line_id.name, self.schedule_id.name)
                )
            vals['destination_account_id'] = account.id
        return vals

    def _create_account_payment(self):
        """Post the Odoo payment behind this voucher and match it where possible."""
        self.ensure_one()
        payment = self.env['account.payment'].sudo().create(self._prepare_payment_vals())
        payment.action_post()
        if self.voucher_type == 'vendor':
            self._reconcile_vendor_payment(payment)
        return payment

    def _reconcile_vendor_payment(self, payment):
        """Match the net payment plus the withheld tax against the gross vendor bill."""
        self.ensure_one()
        bill = self.invoice_id
        if not bill or bill.state != 'posted':
            return
        payable = lambda line: (
            line.account_id.account_type == 'liability_payable' and not line.reconciled
        )
        bill_lines = bill.line_ids.sudo().filtered(payable)
        payment_lines = payment.move_id.line_ids.sudo().filtered(payable)
        if not bill_lines or not payment_lines:
            return
        to_reconcile = bill_lines + payment_lines
        withholding = self.schedule_id._post_withholding_entry(bill, self.payment_date)
        if withholding:
            to_reconcile += withholding.line_ids.sudo().filtered(payable)
        to_reconcile.reconcile()

    def _check_payable(self):
        """Refuse payments that would post the tax withheld to the wrong side."""
        self.ensure_one()
        if self.voucher_type == 'vendor' and self.schedule_id.tax_line_ids:
            # Without the gross bill there is no payable to withhold against, so the
            # deduction could not be moved onto the tax payable accounts.
            if not self.invoice_id or self.invoice_id.state != 'posted':
                raise UserError(
                    "%s has statutory deductions but %s has no posted vendor bill, so "
                    "the tax withheld cannot be recorded. Post the vendor bill (goods "
                    "must be received first) before paying the vendor."
                    % (self.name, self.payment_request_id.name)
                )
        if self.voucher_type == 'tax':
            vendor_voucher = self.schedule_id.voucher_ids.filtered(
                lambda v: v.voucher_type == 'vendor' and v.state != 'cancelled'
            )[:1]
            if vendor_voucher and vendor_voucher.state != 'paid':
                raise UserError(
                    "The tax on %s has not been withheld yet: pay the vendor voucher "
                    "%s before remitting to %s."
                    % (self.schedule_id.name, vendor_voucher.name, self.partner_id.display_name)
                )

    def action_register_payment(self):
        for rec in self:
            if rec.state != 'audited':
                raise UserError(
                    "%s can only be paid once it has been audited." % rec.name
                )
            rec._check_payable()
            if not rec.payment_reference:
                raise UserError(
                    "Enter the payment reference on %s before marking it paid." % rec.name
                )
            if not rec.payment_journal_id:
                raise UserError(
                    "Select the payment journal on %s before marking it paid." % rec.name
                )
            if not rec.payment_date:
                rec.payment_date = fields.Date.context_today(rec)
            rec.payment_id = rec._create_account_payment()
            rec.state = 'paid'
            rec._log_approval(
                'Payment Registered', self.env.user, fields.Datetime.now(),
                'Reference: %s' % rec.payment_reference,
            )
            rec.message_post(
                body="Voucher paid by %s. Reference %s, journal %s, Odoo payment %s."
                     % (self.env.user.display_name, rec.payment_reference,
                        rec.payment_journal_id.display_name, rec.payment_id.name)
            )
            rec.schedule_id._settle_if_fully_paid()

    def action_view_payment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'res_id': self.payment_id.id,
            'view_mode': 'form',
        }

    def action_print_voucher(self):
        return self.env.ref('nbet_treasury.action_report_payment_voucher').report_action(self)

    def action_cancel(self):
        for rec in self:
            if rec.state in ('audited', 'paid'):
                raise UserError(
                    "Voucher %s has been %s and can no longer be cancelled."
                    % (rec.name, 'paid' if rec.state == 'paid' else 'audited')
                )
        self.write({'state': 'cancelled'})


class PaymentVoucherApproval(models.Model):
    _name = 'nbet.payment.voucher.approval'
    _description = 'Payment Voucher Approval History'
    _order = 'voucher_id, sequence, id'

    voucher_id = fields.Many2one(
        'nbet.payment.voucher',
        string='Voucher',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    stage = fields.Char(string='Approval Stage', required=True, readonly=True)
    user_id = fields.Many2one('res.users', string='Approving Officer', readonly=True)
    user_login = fields.Char(string='User ID', readonly=True)
    approval_datetime = fields.Datetime(string='Date & Time', readonly=True)
    notes = fields.Text(readonly=True)
    auth_code = fields.Char(
        string='Digital Authentication Record',
        readonly=True,
        copy=False,
    )
    auth_valid = fields.Boolean(compute='_compute_auth_valid', string='Valid')

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            line.sudo().auth_code = line._build_auth_code()
        return lines

    def _auth_payload(self):
        self.ensure_one()
        return '|'.join([
            self.voucher_id.name or '',
            self.stage or '',
            self.user_login or '',
            fields.Datetime.to_string(self.approval_datetime) or '',
        ])

    def _build_auth_code(self):
        self.ensure_one()
        return hmac(
            self.env(su=True), 'nbet-voucher-approval', self._auth_payload()
        )[:32].upper()

    @api.depends('stage', 'user_login', 'approval_datetime', 'auth_code')
    def _compute_auth_valid(self):
        for rec in self:
            rec.auth_valid = bool(rec.auth_code) and consteq(rec.auth_code, rec._build_auth_code())
