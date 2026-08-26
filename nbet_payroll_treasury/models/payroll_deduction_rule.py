# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PayrollDeductionRule(models.Model):
    _name = 'nbet.payroll.deduction.rule'
    _description = 'Payroll Statutory Deduction Rule'
    _order = 'sequence, id'

    name = fields.Char(
        required=True,
        help='Label carried onto the remittance voucher, e.g. "PAYE - FIRS".',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
    )
    salary_rule_ids = fields.Many2many(
        'hr.salary.rule',
        string='Salary Rules',
        required=True,
        help='Payslip rules whose amounts are withheld from the employee and '
             'remitted to the body below. Several rules can feed one remittance, '
             'e.g. employee and employer pension contributions.',
    )
    tax_type = fields.Selection([
        ('vat', 'VAT'),
        ('wht', 'Withholding Tax'),
        ('other', 'Other Statutory Deduction'),
    ], string='Deduction Type', required=True, default='other')
    partner_id = fields.Many2one(
        'res.partner',
        string='Remitted To',
        required=True,
        help='Body the deduction is paid over to, e.g. FIRS or the pension '
             'fund administrator.',
    )
    tax_payable_account_id = fields.Many2one(
        'account.account',
        string='Payable Account',
        domain="[('account_type', '=', 'liability_current'), ('deprecated', '=', False)]",
        help='Liability account the withheld amount sits in until it is remitted. '
             'Normally the credit account of the salary rules above.',
    )
    note = fields.Text(string='Notes')

    @api.constrains('salary_rule_ids')
    def _check_rules_not_shared(self):
        """A salary rule may only feed one remittance, or it would be paid twice."""
        for rec in self:
            clashes = self.search([
                ('id', '!=', rec.id),
                ('company_id', '=', rec.company_id.id),
                ('salary_rule_ids', 'in', rec.salary_rule_ids.ids),
            ])
            if clashes:
                shared = clashes.salary_rule_ids & rec.salary_rule_ids
                raise ValidationError(
                    "Salary rule(s) %s are already remitted by '%s'. A rule can only "
                    "belong to one deduction rule, otherwise it would be paid over twice."
                    % (', '.join(shared.mapped('name')), clashes[0].name)
                )

    def _amount_for_payslips(self, payslips):
        """What this rule withholds across the given payslips.

        Payroll deduction lines are negative, so the magnitude is what gets
        remitted.
        """
        self.ensure_one()
        lines = payslips.mapped('line_ids').filtered(
            lambda l: l.salary_rule_id in self.salary_rule_ids
        )
        return abs(sum(lines.mapped('total')))

    @api.model
    def _rules_for_company(self, company):
        return self.search([('company_id', '=', company.id)])
