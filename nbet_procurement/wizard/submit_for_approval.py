# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class SubmitForApprovalWizard(models.TransientModel):
    _name = 'nbet.submit.approval.wizard'
    _description = 'Submit Purchase Order for NBET Approval'

    purchase_order_id = fields.Many2one('purchase.order', required=True)
    approval_authority = fields.Selection(related='purchase_order_id.nbet_approval_authority')
    amount_total = fields.Monetary(related='purchase_order_id.amount_total')
    currency_id = fields.Many2one(related='purchase_order_id.currency_id')
    procurement_category = fields.Selection(related='purchase_order_id.nbet_procurement_category')
    justification = fields.Text(string='Justification / Notes')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'purchase.order':
            res['purchase_order_id'] = self.env.context.get('active_id')
        return res

    def action_submit(self):
        self.ensure_one()
        po = self.purchase_order_id
        if not po.nbet_procurement_category:
            raise UserError("Please set the Procurement Category on the purchase order first.")
        po.message_post(
            body="<p><strong>Submitted for NBET Procurement Approval</strong></p>"
                 "<p>Authority: %s</p><p>Amount: %s %s</p><p>Justification: %s</p>" % (
                     dict(po._fields['nbet_approval_authority'].selection).get(
                         po.nbet_approval_authority, 'N/A'),
                     po.currency_id.symbol,
                     '{:,.2f}'.format(po.amount_total),
                     self.justification or 'N/A',
                 ),
        )
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'message': 'Purchase order submitted for approval.',
            'type': 'success',
        }}
