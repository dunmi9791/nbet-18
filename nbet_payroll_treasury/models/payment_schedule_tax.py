# -*- coding: utf-8 -*-
from odoo import models, fields, api


class PaymentScheduleTax(models.Model):
    _inherit = 'nbet.payment.schedule.tax'

    payroll_deduction_rule_id = fields.Many2one(
        'nbet.payroll.deduction.rule',
        string='Payroll Deduction Rule',
        readonly=True,
        ondelete='set null',
        help='Set when this deduction was totalled off the payslips of a payroll '
             'batch rather than derived from a rate.',
    )

    # A payroll deduction is the sum of what the payslips actually withheld, so
    # it carries no rate to recompute from. Leave those lines as they were
    # created; recomputing would zero them.
    @api.depends('schedule_id.amount')
    def _compute_base_amount(self):
        from_payroll = self.filtered('payroll_deduction_rule_id')
        for rec in from_payroll:
            rec.base_amount = rec.base_amount
        super(PaymentScheduleTax, self - from_payroll)._compute_base_amount()

    @api.depends('base_amount', 'rate')
    def _compute_amount(self):
        from_payroll = self.filtered('payroll_deduction_rule_id')
        for rec in from_payroll:
            rec.amount = rec.amount
        super(PaymentScheduleTax, self - from_payroll)._compute_amount()

    @api.depends('tax_type', 'rate')
    def _compute_name(self):
        from_payroll = self.filtered('payroll_deduction_rule_id')
        for rec in from_payroll:
            rec.name = rec.name or rec.payroll_deduction_rule_id.name
        super(PaymentScheduleTax, self - from_payroll)._compute_name()
