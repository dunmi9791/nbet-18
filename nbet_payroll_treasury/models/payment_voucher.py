# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class PaymentVoucher(models.Model):
    _inherit = 'nbet.payment.voucher'

    voucher_type = fields.Selection(
        selection_add=[('payroll', 'Employee Salary')],
        ondelete={'payroll': 'cascade'},
    )
    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Payslip',
        readonly=True,
        ondelete='set null',
        index='btree_not_null',
    )
    employee_id = fields.Many2one(
        related='payslip_id.employee_id', store=True, string='Employee',
    )
    payslip_run_id = fields.Many2one(
        related='schedule_id.payslip_run_id', store=True, string='Payroll Batch',
    )

    # ------------------------------------------------------------------
    # Payment
    # ------------------------------------------------------------------
    def _salary_payable_account(self):
        """Where the employee's net pay is sitting until it is disbursed.

        Prefer the account configured on the company; otherwise take the credit
        account of the payslip's NET rule, which is what the payroll entry
        credited.
        """
        self.ensure_one()
        company = self.payslip_id.sudo().company_id or self.env.company
        configured = company.sudo().nbet_salary_payable_account_id
        if configured:
            return configured
        net_line = self.payslip_id.sudo().line_ids.filtered(lambda l: l.code == 'NET')[:1]
        return net_line.salary_rule_id.account_credit

    def _payment_destination_account(self):
        self.ensure_one()
        if self.voucher_type != 'payroll':
            return super()._payment_destination_account()
        # An empty account leaves Odoo to use the payee's payable account, which
        # is a valid setup for a company that does not park salaries separately.
        return self._salary_payable_account()

    def _check_payable(self):
        self.ensure_one()
        if self.voucher_type == 'tax' and self.schedule_id.source_type == 'payroll':
            # The deduction only exists because the salaries were paid net of
            # it, so the salary vouchers clear first.
            unpaid = self.schedule_id.voucher_ids.filtered(
                lambda v: v.voucher_type == 'payroll' and v.state not in ('paid', 'cancelled')
            )
            if unpaid:
                raise UserError(
                    "%s of the batch's salary voucher(s) are still unpaid, so the "
                    "deduction has not been withheld yet. Pay the salaries before "
                    "remitting to %s." % (len(unpaid), self.partner_id.display_name)
                )
            return super()._check_payable()
        if self.voucher_type != 'payroll':
            return super()._check_payable()
        if not self.payslip_id:
            raise UserError("%s has no payslip attached." % self.name)
        if self.payslip_id.sudo().state not in ('done', 'paid'):
            raise UserError(
                "Payslip %s is %s, not validated, so %s cannot be paid."
                % (self.payslip_id.number or self.payslip_id.name,
                   self.payslip_id.sudo().state, self.name)
            )

    def _on_voucher_paid(self):
        """Mark the payslip paid in payroll, and clear its payable if we can."""
        res = super()._on_voucher_paid()
        for rec in self.filtered(lambda v: v.voucher_type == 'payroll' and v.payslip_id):
            payslip = rec.payslip_id.sudo()
            if payslip.state != 'paid':
                payslip.with_context(nbet_treasury_settlement=True).action_payslip_paid()
            rec._reconcile_payslip_payment()
            rec.message_post(
                body="Payslip %s marked paid in Payroll."
                     % (payslip.number or payslip.display_name)
            )
        return res

    def _reconcile_payslip_payment(self):
        """Match the disbursement against the payroll entry's salary payable line.

        Best effort: it only fires where the payroll entry is posted onto a
        reconcilable account and the payee is identifiable on it. Anything else
        is left for the accountant, rather than guessing at a match.
        """
        self.ensure_one()
        move = self.payslip_id.sudo().move_id
        account = self._salary_payable_account()
        if not move or move.state != 'posted' or not account or not account.reconcile:
            return
        matches = lambda line: (
            line.account_id == account
            and line.partner_id == self.partner_id
            and not line.reconciled
        )
        payslip_lines = move.line_ids.sudo().filtered(matches)
        payment_lines = self.payment_id.move_id.line_ids.sudo().filtered(matches)
        if not payslip_lines or not payment_lines:
            return
        (payslip_lines + payment_lines).reconcile()

    def action_view_payslip(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'res_id': self.payslip_id.id,
            'view_mode': 'form',
        }
