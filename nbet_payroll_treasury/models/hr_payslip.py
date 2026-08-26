# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    payment_voucher_id = fields.Many2one(
        'nbet.payment.voucher',
        string='Payment Voucher',
        compute='_compute_payment_voucher_id',
        help='Treasury voucher raised to pay this payslip.',
    )
    voucher_state = fields.Selection(
        related='payment_voucher_id.state', string='Voucher Status', readonly=True,
    )
    run_approval_state = fields.Selection(
        related='payslip_run_id.approval_state', string='Batch Payment Approval',
        readonly=True,
    )

    def action_payslip_paid(self):
        """Payment is the treasury's to record once the batch is in the chain."""
        blocked = self.filtered(
            lambda s: s.run_approval_state in ('md_approval', 'md_approved', 'treasury')
        )
        if blocked and not self.env.context.get('nbet_treasury_settlement'):
            raise UserError(
                "These payslips are awaiting payment through Treasury, and are "
                "marked paid when their payment vouchers are paid:\n%s"
                % '\n'.join(sorted(blocked.mapped('employee_id.name')))
            )
        return super().action_payslip_paid()

    def _compute_payment_voucher_id(self):
        """Look the voucher up from the treasury side.

        Kept unstored so the link needs no write back from voucher generation,
        which runs as a treasury user with no payroll write access.
        """
        vouchers = self.env['nbet.payment.voucher'].sudo().search([
            ('payslip_id', 'in', self._origin.ids),
            ('state', '!=', 'cancelled'),
        ])
        by_payslip = {v.payslip_id.id: v.id for v in vouchers}
        for slip in self:
            slip.payment_voucher_id = by_payslip.get(slip.id, False)

    def action_view_payment_voucher(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.payment.voucher',
            'res_id': self.payment_voucher_id.id,
            'view_mode': 'form',
        }
