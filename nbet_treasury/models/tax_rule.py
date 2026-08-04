# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class TaxRule(models.Model):
    _name = 'nbet.tax.rule'
    _description = 'Statutory Deduction Rule'
    _order = 'sequence, id'

    name = fields.Char(
        required=True,
        help='Label used on the deduction line, e.g. "VAT 7.5%".',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    tax_type = fields.Selection([
        ('vat', 'VAT'),
        ('wht', 'Withholding Tax'),
        ('other', 'Other Statutory Deduction'),
    ], string='Deduction Type', required=True, default='vat')
    rate = fields.Float(string='Rate (%)', digits=(16, 3), required=True, default=7.5)
    tax_body_id = fields.Many2one(
        'res.partner',
        string='Tax Body',
        required=True,
        help='Statutory body the deduction is remitted to, e.g. FIRS.',
    )
    tax_payable_account_id = fields.Many2one(
        'account.account',
        string='Tax Payable Account',
        domain="[('account_type', '=', 'liability_current'), ('deprecated', '=', False)]",
        help='Liability account carrying the amount withheld from the vendor until it '
             'is remitted to the tax body. Credited when the vendor is paid, debited '
             'when the remittance voucher is paid.',
    )
    category = fields.Selection([
        ('goods', 'Goods'),
        ('works', 'Works'),
        ('non_consultant', 'Non-Consultant Services'),
        ('consultant', 'Consultant Services'),
    ], string='Contract Category',
        help='Leave empty to apply the rule to every contract category. '
             'Set a category to apply it only to contracts of that category.')
    note = fields.Text(string='Notes')

    @api.constrains('rate')
    def _check_rate(self):
        for rec in self:
            if rec.rate <= 0 or rec.rate > 100:
                raise ValidationError("The deduction rate must be between 0 and 100%.")

    @api.model
    def _rules_for_category(self, category):
        """Rules that apply to a contract category, plus the category-agnostic ones."""
        return self.search([('category', 'in', [category, False] if category else [False])])

    def _prepare_tax_line_vals(self):
        self.ensure_one()
        return {
            'tax_type': self.tax_type,
            'name': self.name,
            'rate': self.rate,
            'tax_body_id': self.tax_body_id.id,
            'tax_payable_account_id': self.tax_payable_account_id.id,
            'tax_rule_id': self.id,
        }
