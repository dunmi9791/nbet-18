# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class NbetPaymentAdvice(models.Model):
    _inherit = 'nbet.payment.advice'

    payment_schedule_id = fields.Many2one(
        'nbet.payment.schedule',
        string='Payment Schedule',
        readonly=True,
        copy=False,
        index='btree_not_null',
    )
    schedule_state = fields.Selection(
        related='payment_schedule_id.state', string='Treasury Status', readonly=True,
    )
    voucher_count = fields.Integer(compute='_compute_voucher_count')

    treasury_submitted_by_id = fields.Many2one(
        'res.users', string='Sent to Treasury By', readonly=True, copy=False,
    )
    treasury_submitted_date = fields.Datetime(
        string='Sent to Treasury On', readonly=True, copy=False,
    )

    @api.depends('payment_schedule_id.voucher_ids')
    def _compute_voucher_count(self):
        for rec in self:
            rec.voucher_count = len(rec.payment_schedule_id.voucher_ids)

    # ------------------------------------------------------------------
    # Hand-over to treasury
    # ------------------------------------------------------------------
    def _prepare_payment_schedule_vals(self):
        self.ensure_one()
        return {
            'source_type': 'power_billing',
            'payment_advice_id': self.id,
            'description': 'GENCO payments - advice %s (%s)' % (
                self.name, self.billing_cycle_id.name,
            ),
            'amount': self.total_advice_amount,
            'currency_id': self.currency_id.id,
        }

    def action_send_to_treasury(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_settlement_manager'):
            raise UserError(
                'Only Settlement Managers can send a payment advice to Treasury.'
            )
        for rec in self:
            if rec.state != 'md_approved':
                raise UserError(
                    '%s must be approved by the Managing Director before it '
                    'goes to Treasury.' % rec.name
                )
            if rec.payment_schedule_id:
                raise UserError(
                    '%s is already with treasury on payment schedule %s.'
                    % (rec.name, rec.payment_schedule_id.name)
                )
            missing = rec.line_ids.filtered(
                lambda l: l.advice_amount and not l.partner_id)
            if missing:
                raise UserError(
                    'These GENCOs have no Odoo contact, so no payee can be put '
                    'on their voucher. Set a partner on the participant record '
                    'first:\n%s'
                    % '\n'.join(sorted(missing.mapped('participant_id.name')))
                )
            # Billing raises the schedule but does not work in treasury, so it
            # has no create rights of its own on the payment schedule.
            schedule = self.env['nbet.payment.schedule'].sudo().create(
                rec._prepare_payment_schedule_vals()
            )
            rec.write({
                'state': 'sent_to_treasury',
                'payment_schedule_id': schedule.id,
                'treasury_submitted_by_id': self.env.user.id,
                'treasury_submitted_date': fields.Datetime.now(),
            })
            rec.message_post(
                body='Payment advice sent to Treasury by %s on payment schedule '
                     '%s for a total of %s.'
                     % (self.env.user.display_name, schedule.name,
                        rec.total_advice_amount)
            )
            schedule.message_post(
                body='Raised from payment advice %s (cycle %s), approved by the '
                     'Head of OCMA (%s) and the Managing Director (%s).'
                     % (rec.name, rec.billing_cycle_id.name,
                        rec.ocma_approver_id.display_name,
                        rec.md_approver_id.display_name)
            )

    # ------------------------------------------------------------------
    # Settlement, driven from the treasury vouchers
    # ------------------------------------------------------------------
    def _mark_paid_from_treasury(self):
        self.ensure_one()
        self.write({'state': 'paid'})
        self.message_post(
            body='All treasury vouchers of schedule %s paid — payment advice '
                 'settled.' % self.payment_schedule_id.name
        )

    def action_cancel(self):
        for rec in self:
            if rec.payment_schedule_id and rec.payment_schedule_id.state != 'cancelled':
                raise UserError(
                    '%s is with Treasury on payment schedule %s. Cancel the '
                    'schedule there first.'
                    % (rec.name, rec.payment_schedule_id.name)
                )
        return super().action_cancel()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_view_payment_schedule(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payment Schedule',
            'res_model': 'nbet.payment.schedule',
            'res_id': self.payment_schedule_id.id,
            'view_mode': 'form',
        }

    def action_view_vouchers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payment Vouchers',
            'res_model': 'nbet.payment.voucher',
            'view_mode': 'list,form',
            'domain': [('schedule_id', '=', self.payment_schedule_id.id)],
        }
