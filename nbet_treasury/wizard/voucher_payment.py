# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class VoucherPayment(models.TransientModel):
    """Pay a batch of audited vouchers off one bank instruction.

    A payment schedule can carry hundreds of vouchers - a payroll batch raises
    one per employee - which the treasury settles as a single transfer against
    one schedule sent to the bank. This records that in one step rather than
    voucher by voucher.
    """
    _name = 'nbet.voucher.payment'
    _description = 'Register Voucher Payments'

    voucher_ids = fields.Many2many(
        'nbet.payment.voucher',
        string='Vouchers',
        required=True,
        default=lambda self: self._default_voucher_ids(),
    )
    voucher_count = fields.Integer(compute='_compute_totals')
    total_amount = fields.Float(compute='_compute_totals', string='Total to Pay')
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        required=True,
        domain="[('type', 'in', ('bank', 'cash'))]",
    )
    payment_date = fields.Date(
        string='Payment Date',
        required=True,
        default=fields.Date.context_today,
    )
    payment_reference = fields.Char(
        string='Payment Reference',
        required=True,
        help='Bank instruction reference. It is stamped on every voucher below.',
    )

    @api.model
    def _default_voucher_ids(self):
        vouchers = self.env['nbet.payment.voucher'].browse(
            self.env.context.get('active_ids', [])
        )
        return [(6, 0, vouchers.filtered(lambda v: v.state == 'audited').ids)]

    @api.depends('voucher_ids')
    def _compute_totals(self):
        for rec in self:
            rec.voucher_count = len(rec.voucher_ids)
            rec.total_amount = sum(rec.voucher_ids.mapped('amount'))

    def action_register_payments(self):
        self.ensure_one()
        not_audited = self.voucher_ids.filtered(lambda v: v.state != 'audited')
        if not_audited:
            raise UserError(
                "These vouchers have not been audited and cannot be paid:\n%s"
                % '\n'.join(not_audited.mapped('name'))
            )
        if not self.voucher_ids:
            raise UserError("Select at least one audited voucher to pay.")

        # Vendor vouchers must clear before their remittances, which is the
        # order action_register_payment expects.
        ordered = self.voucher_ids.sorted(key=lambda v: v.voucher_type == 'tax')
        for voucher in ordered:
            voucher.write({
                'payment_journal_id': self.payment_journal_id.id,
                'payment_date': self.payment_date,
                'payment_reference': self.payment_reference,
            })
            voucher.action_register_payment()
        return {'type': 'ir.actions.act_window_close'}
