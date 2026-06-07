# -*- coding: utf-8 -*-
from odoo import models, fields


class PaymentRequestInherit(models.Model):
    _inherit = 'nbet.payment.request'

    payment_schedule_id = fields.Many2one(
        'nbet.payment.schedule',
        string='Payment Schedule',
        readonly=True,
    )

    def action_send_to_treasury(self):
        for rec in self:
            schedule = self.env['nbet.payment.schedule'].create({
                'payment_request_id': rec.id,
            })
            rec.write({
                'state': 'sent_to_treasury',
                'payment_schedule_id': schedule.id,
            })
            rec.contract_award_id.write({'state': 'payment_processing'})

    def action_view_payment_schedule(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.payment.schedule',
            'res_id': self.payment_schedule_id.id,
            'view_mode': 'form',
        }
