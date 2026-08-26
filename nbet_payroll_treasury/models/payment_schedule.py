# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class PaymentSchedule(models.Model):
    _inherit = 'nbet.payment.schedule'

    source_type = fields.Selection(
        selection_add=[('payroll', 'Payroll Batch')],
        ondelete={'payroll': 'set default'},
    )
    payslip_run_id = fields.Many2one(
        'hr.payslip.run',
        string='Payroll Batch',
        readonly=True,
        copy=False,
        index='btree_not_null',
    )
    payslip_count = fields.Integer(compute='_compute_payslip_count')

    @api.depends('payslip_run_id.slip_ids')
    def _compute_payslip_count(self):
        for rec in self:
            rec.payslip_count = len(rec.payslip_run_id.sudo()._treasury_payslips()) \
                if rec.payslip_run_id else 0

    # ------------------------------------------------------------------
    # Source document
    # ------------------------------------------------------------------
    def _source_document_name(self):
        self.ensure_one()
        if self.source_type == 'payroll':
            return 'Payroll batch %s' % self.payslip_run_id.name
        return super()._source_document_name()

    def _source_approval_history(self):
        self.ensure_one()
        if self.source_type != 'payroll':
            return super()._source_approval_history()
        run = self.payslip_run_id
        return [
            ('Payroll Batch Submitted', run.submitted_by_id, run.submitted_date),
            ('MD Approval', run.md_approver_id, run.md_approval_date),
            ('Sent to Treasury', run.treasury_submitted_by_id, run.treasury_submitted_date),
        ]

    def _uses_default_deductions(self):
        # A payroll batch brings its deductions off the payslips, not off the
        # contract tax rules.
        self.ensure_one()
        if self.source_type == 'payroll':
            return False
        return super()._uses_default_deductions()

    # ------------------------------------------------------------------
    # Vouchers: one per payslip, plus one per statutory deduction
    # ------------------------------------------------------------------
    def _check_voucher_generation(self):
        self.ensure_one()
        if self.source_type != 'payroll':
            return super()._check_voucher_generation()
        if not self.payslip_run_id:
            raise UserError("%s has no payroll batch attached." % self.name)
        # Re-run the batch's own checks: an employee may have lost their work
        # contact, or a payslip been cancelled, since the batch was sent over.
        # Sudo throughout: the finance officer raising the vouchers is not a
        # payroll user, but does need the figures off the payslips.
        self.payslip_run_id.sudo()._check_ready_for_treasury()

    def _prepare_payslip_voucher_vals(self, payslip):
        self.ensure_one()
        payslip = payslip.sudo()
        employee = payslip.employee_id
        return {
            'schedule_id': self.id,
            'voucher_type': 'payroll',
            'payslip_id': payslip.id,
            'partner_id': employee.work_contact_id.id,
            'bank_account': employee.bank_account_id.acc_number or '',
            'description': 'Salary %s - %s' % (
                payslip.number or payslip.name, employee.name,
            ),
            'amount': payslip.net_wage,
            'payment_journal_id': self.payment_journal_id.id,
            'generated_by_id': self.env.user.id,
            'generated_on': fields.Datetime.now(),
        }

    def _prepare_voucher_vals_list(self):
        self.ensure_one()
        if self.source_type != 'payroll':
            return super()._prepare_voucher_vals_list()
        payslips = self.payslip_run_id.sudo()._treasury_payslips()
        return (
            [self._prepare_payslip_voucher_vals(slip) for slip in payslips]
            + [self._prepare_tax_voucher_vals(line) for line in self.tax_line_ids]
        )

    def _prepare_tax_voucher_vals(self, tax_line):
        vals = super()._prepare_tax_voucher_vals(tax_line)
        if self.source_type == 'payroll':
            vals['description'] = '%s remittance for payroll batch %s' % (
                tax_line.name, self.payslip_run_id.name,
            )
        return vals

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------
    def _settle_source_document(self, payment_date, reference):
        self.ensure_one()
        if self.source_type != 'payroll':
            return super()._settle_source_document(payment_date, reference)
        self.payslip_run_id.sudo()._mark_paid_from_treasury()

    def action_view_payslips(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payslips',
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'domain': [('payslip_run_id', '=', self.payslip_run_id.id)],
        }
