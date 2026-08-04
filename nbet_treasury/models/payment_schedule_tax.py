# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PaymentScheduleTax(models.Model):
    _name = 'nbet.payment.schedule.tax'
    _description = 'Payment Schedule Statutory Deduction'
    _order = 'schedule_id, sequence, id'

    sequence = fields.Integer(default=10)
    schedule_id = fields.Many2one(
        'nbet.payment.schedule',
        string='Payment Schedule',
        required=True,
        ondelete='cascade',
        index=True,
    )
    currency_id = fields.Many2one(related='schedule_id.currency_id')
    tax_type = fields.Selection([
        ('vat', 'VAT'),
        ('wht', 'Withholding Tax'),
        ('other', 'Other Statutory Deduction'),
    ], string='Deduction Type', required=True, default='vat')
    name = fields.Char(
        string='Description',
        compute='_compute_name',
        store=True,
        readonly=False,
    )
    rate = fields.Float(string='Rate (%)', digits=(16, 3), default=7.5)
    base_amount = fields.Float(
        string='Base Amount (NGN)',
        compute='_compute_base_amount',
        store=True,
        readonly=False,
    )
    amount = fields.Float(
        string='Deduction Amount (NGN)',
        compute='_compute_amount',
        store=True,
        readonly=False,
    )
    tax_body_id = fields.Many2one(
        'res.partner',
        string='Tax Body',
        required=True,
        help='Statutory body the deduction is remitted to, e.g. FIRS.',
    )
    voucher_id = fields.Many2one(
        'nbet.payment.voucher',
        string='Remittance Voucher',
        readonly=True,
        copy=False,
        ondelete='set null',
    )
    tax_payable_account_id = fields.Many2one(
        'account.account',
        string='Tax Payable Account',
        domain="[('account_type', '=', 'liability_current'), ('deprecated', '=', False)]",
        help='Liability account credited when the vendor is paid and debited when '
             'this deduction is remitted to the tax body.',
    )
    tax_rule_id = fields.Many2one(
        'nbet.tax.rule',
        string='Source Rule',
        readonly=True,
        ondelete='set null',
        help='Configuration rule this line was pre-filled from.',
    )

    @api.depends('tax_type', 'rate')
    def _compute_name(self):
        labels = dict(self._fields['tax_type'].selection)
        for rec in self:
            rec.name = '%s @ %s%%' % (labels.get(rec.tax_type, ''), rec.rate)

    @api.depends('schedule_id.amount')
    def _compute_base_amount(self):
        for rec in self:
            rec.base_amount = rec.schedule_id.amount

    @api.depends('base_amount', 'rate')
    def _compute_amount(self):
        for rec in self:
            rec.amount = rec.base_amount * rec.rate / 100.0

    @api.constrains('rate', 'amount', 'base_amount')
    def _check_amounts(self):
        for rec in self:
            if rec.rate < 0 or rec.rate > 100:
                raise ValidationError("The deduction rate must be between 0 and 100%.")
            if rec.amount < 0:
                raise ValidationError("The deduction amount cannot be negative.")
            if rec.base_amount < 0:
                raise ValidationError("The base amount cannot be negative.")
