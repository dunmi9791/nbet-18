# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools import float_compare


class PaymentSchedule(models.Model):
    _inherit = 'nbet.payment.schedule'

    source_type = fields.Selection(
        selection_add=[('power_billing', 'GENCO Payment Advice')],
        ondelete={'power_billing': 'set default'},
    )
    payment_advice_id = fields.Many2one(
        'nbet.payment.advice',
        string='Payment Advice',
        readonly=True,
        copy=False,
        index='btree_not_null',
    )
    advice_line_count = fields.Integer(compute='_compute_advice_line_count')

    @api.depends('payment_advice_id.line_ids')
    def _compute_advice_line_count(self):
        for rec in self:
            rec.advice_line_count = len(rec.payment_advice_id.line_ids)

    # ------------------------------------------------------------------
    # Source document
    # ------------------------------------------------------------------
    def _source_document_name(self):
        self.ensure_one()
        if self.source_type == 'power_billing':
            return 'Payment advice %s' % self.payment_advice_id.name
        return super()._source_document_name()

    def _source_approval_history(self):
        self.ensure_one()
        if self.source_type != 'power_billing':
            return super()._source_approval_history()
        advice = self.payment_advice_id
        return [
            ('Payment Advice Prepared', advice.submitted_by_id, advice.submitted_date),
            ('Head of OCMA Approval', advice.ocma_approver_id, advice.ocma_approval_date),
            ('MD Approval', advice.md_approver_id, advice.md_approval_date),
            ('Sent to Treasury', advice.treasury_submitted_by_id,
             advice.treasury_submitted_date),
        ]

    def _uses_default_deductions(self):
        # The advice amounts are the committee's disbursement figures; the tax
        # obligations of the energy purchases already sit inside the posted
        # vendor bills, which the payment reconciles at face value.
        self.ensure_one()
        if self.source_type == 'power_billing':
            return False
        return super()._uses_default_deductions()

    # ------------------------------------------------------------------
    # Vouchers: one per GENCO advice line
    # ------------------------------------------------------------------
    def _check_voucher_generation(self):
        self.ensure_one()
        if self.source_type != 'power_billing':
            return super()._check_voucher_generation()
        # Sudo throughout: the finance officer raising the vouchers is not a
        # billing user, but does need the figures off the advice.
        advice = self.payment_advice_id.sudo()
        if not advice:
            raise UserError('%s has no payment advice attached.' % self.name)
        if advice.state != 'sent_to_treasury':
            raise UserError(
                'Payment advice %s is %s, not with treasury, so no vouchers '
                'can be raised for it.' % (advice.name, advice.state)
            )
        lines = advice.line_ids.filtered(lambda l: l.advice_amount)
        if not lines:
            raise UserError(
                'Payment advice %s advises no payment to any GENCO.' % advice.name
            )
        missing_payee = lines.filtered(lambda l: not l.partner_id)
        if missing_payee:
            raise UserError(
                'These GENCOs have no Odoo contact, so no payee can be put on '
                'their voucher:\n%s'
                % '\n'.join(sorted(missing_payee.mapped('participant_id.name')))
            )
        # Bills may have been settled by other means since MD approval — refuse
        # to pay a GENCO more than it is still owed today.
        rounding = self.currency_id.rounding or 0.01
        stale = [
            line.participant_id.display_name
            for line in lines
            if float_compare(
                line.advice_amount,
                sum(m._nbet_open_amount() for m in line.vendor_bill_ids),
                precision_rounding=rounding,
            ) > 0
        ]
        if stale:
            raise UserError(
                'The advised amounts for these GENCOs now exceed their open '
                'vendor bill balances — the bills were partly settled since the '
                'advice was approved. Return the advice to billing:\n%s'
                % '\n'.join(sorted(stale))
            )

    def _prepare_genco_voucher_vals(self, line):
        self.ensure_one()
        line = line.sudo()
        return {
            'schedule_id': self.id,
            'voucher_type': 'genco',
            'advice_line_id': line.id,
            'partner_id': line.partner_id.id,
            'description': 'GENCO payment %s - %s (%s)' % (
                line.advice_id.name, line.participant_id.display_name,
                line.advice_id.billing_cycle_id.name,
            ),
            'amount': line.advice_amount,
            'payment_journal_id': self.payment_journal_id.id,
            'generated_by_id': self.env.user.id,
            'generated_on': fields.Datetime.now(),
        }

    def _prepare_voucher_vals_list(self):
        self.ensure_one()
        if self.source_type != 'power_billing':
            return super()._prepare_voucher_vals_list()
        lines = self.payment_advice_id.sudo().line_ids.filtered(
            lambda l: l.advice_amount)
        return [self._prepare_genco_voucher_vals(line) for line in lines]

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------
    def _settle_source_document(self, payment_date, reference):
        self.ensure_one()
        if self.source_type != 'power_billing':
            return super()._settle_source_document(payment_date, reference)
        self.payment_advice_id.sudo()._mark_paid_from_treasury()

    def action_view_advice_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Advice Lines',
            'res_model': 'nbet.payment.advice.line',
            'view_mode': 'list',
            'domain': [('advice_id', '=', self.payment_advice_id.id)],
        }
