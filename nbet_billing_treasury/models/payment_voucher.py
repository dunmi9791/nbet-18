# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class PaymentVoucher(models.Model):
    _inherit = 'nbet.payment.voucher'

    # A GENCO advice line can cover several vendor bills partially, so it gets
    # its own voucher type with its own reconciliation instead of the single-bill
    # 'vendor' path.
    voucher_type = fields.Selection(
        selection_add=[('genco', 'GENCO Payment')],
        ondelete={'genco': 'cascade'},
    )
    advice_line_id = fields.Many2one(
        'nbet.payment.advice.line',
        string='Advice Line',
        readonly=True,
        ondelete='set null',
        index='btree_not_null',
    )
    participant_id = fields.Many2one(
        related='advice_line_id.participant_id', store=True, string='GENCO',
    )
    payment_advice_id = fields.Many2one(
        related='schedule_id.payment_advice_id', store=True, string='Payment Advice',
    )

    # ------------------------------------------------------------------
    # Payment
    # ------------------------------------------------------------------
    def _check_payable(self):
        self.ensure_one()
        if self.voucher_type != 'genco':
            return super()._check_payable()
        if not self.advice_line_id:
            raise UserError('%s has no advice line attached.' % self.name)
        bills = self.advice_line_id.sudo().vendor_bill_ids
        open_bills = bills.filtered(
            lambda b: b.state == 'posted' and b.amount_residual)
        if not open_bills:
            raise UserError(
                '%s has no open posted vendor bill left to pay against — the '
                'payment would sit unreconciled on the payable account. Return '
                'the advice to billing.' % self.name
            )

    def _on_voucher_paid(self):
        """Reconcile the disbursement against the GENCO's cycle vendor bills."""
        res = super()._on_voucher_paid()
        for rec in self.filtered(lambda v: v.voucher_type == 'genco' and v.advice_line_id):
            rec._reconcile_genco_payment()
        return res

    def _reconcile_genco_payment(self):
        """Match the payment against the open payable lines of the advice line's
        vendor bills, oldest first.

        Best effort and sudo'd: the treasury officer paying the voucher is not
        an accounting user of the billing documents. Odoo splits the payment
        across the bills through partial reconciliation; anything it cannot
        match is left for the accountant.
        """
        self.ensure_one()
        bills = self.advice_line_id.sudo().vendor_bill_ids.filtered(
            lambda b: b.state == 'posted'
        ).sorted(lambda b: (b.invoice_date or b.date, b.id))
        payable = lambda line: (
            line.account_id.account_type == 'liability_payable'
            and line.partner_id == self.partner_id
            and not line.reconciled
        )
        bill_lines = bills.line_ids.filtered(payable)
        payment_lines = self.payment_id.sudo().move_id.line_ids.filtered(payable)
        if not bill_lines or not payment_lines:
            return
        (bill_lines + payment_lines).reconcile()
        for bill in bills:
            bill.message_post(
                body='Payment voucher %s (%s) applied against this bill.'
                     % (self.name, self.payment_reference or '')
            )
        self.payment_advice_id.sudo().message_post(
            body='Voucher %s paid: %s settled for %s.'
                 % (self.name, self.amount, self.partner_id.display_name)
        )

    def action_view_advice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.payment.advice',
            'res_id': self.payment_advice_id.id,
            'view_mode': 'form',
        }
