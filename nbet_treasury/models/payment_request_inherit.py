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
            
            # Create Vendor Bill from PO
            invoice = False
            po = rec.contract_award_id.purchase_order_id
            if po and po.state in ['purchase', 'done']:
                # action_create_invoice is the standard method for PO to create bill
                action = po.with_context(create_bill=True).action_create_invoice()
                if action and isinstance(action, dict) and action.get('res_id'):
                    invoice = self.env['account.move'].browse(action['res_id'])
                elif action and isinstance(action, dict) and action.get('domain'):
                    # Sometimes it returns an action with a domain if multiple invoices are created or exists
                    invoice = self.env['account.move'].search(action['domain'], limit=1)
                
                if invoice:
                    invoice.write({
                        'nbet_contract_award_id': rec.contract_award_id.id,
                        'ref': rec.name,
                    })
                    # Attach the file from payment request to the invoice if exists
                    if rec.invoice_attachment:
                        self.env['ir.attachment'].create({
                            'name': rec.invoice_attachment_filename or 'Vendor Invoice',
                            'type': 'binary',
                            'datas': rec.invoice_attachment,
                            'res_model': 'account.move',
                            'res_id': invoice.id,
                        })

            rec.write({
                'state': 'sent_to_treasury',
                'payment_schedule_id': schedule.id,
                'invoice_id': invoice.id if invoice else False,
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
