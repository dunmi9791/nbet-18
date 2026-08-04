# -*- coding: utf-8 -*-
"""
NBET Settlement link on Accounting Documents
Every vendor bill (GENCO), customer invoice (DISCO), credit note and journal
entry produced by the settlement process carries a hard link back to the
billing cycle it settles.  This is what allows cash actually received from
DISCOs and cash actually paid to GENCOs to be reported per cycle.
"""
from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = 'account.move'

    nbet_billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='NBET Billing Cycle',
        index='btree_not_null', ondelete='restrict', copy=False, tracking=True,
        help='Billing cycle this document settles. Payments reconciled against '
             'this document are reported on that cycle.',
    )
    nbet_participant_id = fields.Many2one(
        'nbet.market.participant', string='Market Participant',
        index='btree_not_null', copy=False,
    )
    nbet_settlement_role = fields.Selection(
        selection=[
            ('genco', 'GENCO Settlement'),
            ('disco', 'DISCO Settlement'),
            ('subsidy', 'Subsidy / Grant'),
            ('adjustment', 'Adjustment'),
        ],
        string='Settlement Role', copy=False,
    )

    nbet_amount_settled = fields.Monetary(
        string='Settled Amount', compute='_compute_nbet_amount_settled',
        currency_field='company_currency_id',
        help='Portion of this document already paid/received, in company currency.',
    )

    @api.depends('amount_total', 'amount_residual', 'move_type', 'state',
                 'currency_id', 'company_currency_id')
    def _compute_nbet_amount_settled(self):
        for move in self:
            move.nbet_amount_settled = move._nbet_settled_amount()

    def _nbet_settled_amount(self):
        """Amount settled on this document, signed and in company currency.

        Positive for invoices/bills, negative for the matching refunds so that
        a credit note reduces the cycle total it belongs to.  Miscellaneous
        journal entries never carry a settled amount — they are not payable or
        receivable documents.
        """
        self.ensure_one()
        if self.state != 'posted' or not self.is_invoice(include_receipts=True):
            return 0.0
        settled = self.amount_total - self.amount_residual
        if self.currency_id and self.currency_id != self.company_currency_id:
            settled = self.currency_id._convert(
                settled, self.company_currency_id, self.company_id,
                self.invoice_date or self.date or fields.Date.context_today(self),
            )
        return -settled if self.move_type in ('out_refund', 'in_refund') else settled

    def _nbet_total_amount(self):
        """Face value of this document, signed and in company currency."""
        self.ensure_one()
        if self.state != 'posted' or not self.is_invoice(include_receipts=True):
            return 0.0
        total = self.amount_total
        if self.currency_id and self.currency_id != self.company_currency_id:
            total = self.currency_id._convert(
                total, self.company_currency_id, self.company_id,
                self.invoice_date or self.date or fields.Date.context_today(self),
            )
        return -total if self.move_type in ('out_refund', 'in_refund') else total

    def _nbet_open_amount(self):
        """Amount still outstanding on this document, signed and in company currency."""
        self.ensure_one()
        if self.state != 'posted' or not self.is_invoice(include_receipts=True):
            return 0.0
        residual = self.amount_residual
        if self.currency_id and self.currency_id != self.company_currency_id:
            residual = self.currency_id._convert(
                residual, self.company_currency_id, self.company_id,
                self.invoice_date or self.date or fields.Date.context_today(self),
            )
        return -residual if self.move_type in ('out_refund', 'in_refund') else residual

    def action_open_nbet_billing_cycle(self):
        self.ensure_one()
        if not self.nbet_billing_cycle_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.billing.cycle',
            'res_id': self.nbet_billing_cycle_id.id,
            'view_mode': 'form',
        }
