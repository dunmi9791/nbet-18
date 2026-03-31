# -*- coding: utf-8 -*-
"""
NBET Billing Adjustment
Handles prior balances, dispute resolutions, late corrections, and
outstanding balance carry-forwards for both GENCOs and DISCOs.
"""
from odoo import models, fields, api
from odoo.exceptions import UserError


class NbetBillingAdjustment(models.Model):
    _name = 'nbet.billing.adjustment'
    _description = 'NBET Billing Adjustment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'billing_cycle_id desc, participant_id'

    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='restrict', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='Participant',
        required=True, ondelete='restrict', tracking=True,
    )
    participant_role = fields.Selection(
        selection=[('genco', 'GENCO'), ('disco', 'DISCO')],
        string='Role', tracking=True,
    )
    adjustment_type = fields.Selection(
        selection=[
            ('debit', 'Debit (charge participant)'),
            ('credit', 'Credit (reduce charge)'),
            ('prior_period', 'Prior Period Correction'),
            ('dispute', 'Dispute Resolution'),
            ('reconciliation', 'Reconciliation'),
            ('subsidy', 'Subsidy Adjustment'),
            ('grant', 'Grant Adjustment'),
            ('manual', 'Manual Adjustment'),
        ],
        string='Type', required=True, tracking=True,
    )
    reference = fields.Char(string='Reference No.')
    description = fields.Text(string='Description', required=True)
    amount = fields.Float(string='Amount', digits=(16, 2), required=True, tracking=True)
    currency_id = fields.Many2one(
        'res.currency', related='billing_cycle_id.currency_id',
    )
    approval_state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        default='draft', required=True, tracking=True,
    )
    approved_by = fields.Many2one('res.users', string='Approved By', tracking=True)
    approved_date = fields.Datetime(string='Approved On')
    source_document = fields.Char(string='Source Document')
    applied_to_model = fields.Char(
        string='Applied To (Model)',
        help='Technical model name of the record this adjustment was applied to.',
    )
    applied_to_id = fields.Integer(
        string='Applied To (ID)',
        help='Record ID of the target record.',
    )
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry')
    notes = fields.Text(string='Internal Notes')

    @api.onchange('participant_id')
    def _onchange_participant(self):
        if self.participant_id:
            ptype = self.participant_id.participant_type
            if ptype in ('genco', 'disco'):
                self.participant_role = ptype

    def action_submit(self):
        self.write({'approval_state': 'submitted'})

    def action_approve(self):
        if not self.env.user.has_group('nbet_power_billing.group_nbet_settlement_manager'):
            raise UserError('Only Settlement Managers can approve adjustments.')
        self.write({
            'approval_state': 'approved',
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now(),
        })

    def action_reject(self):
        self.write({'approval_state': 'rejected'})
