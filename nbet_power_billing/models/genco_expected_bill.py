# -*- coding: utf-8 -*-
"""
NBET GENCO Expected Bill
The system's computed expected settlement amount for a GENCO for a billing cycle.
Compared against the GENCO's submitted invoice to flag variances.
"""
from odoo import models, fields, api


class NbetGencoExpectedBill(models.Model):
    _name = 'nbet.genco.expected.bill'
    _description = 'NBET GENCO Expected Bill'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'billing_cycle_id desc, participant_id'

    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='cascade', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='GENCO',
        required=True, ondelete='restrict',
    )
    contract_id = fields.Many2one('nbet.genco.contract', string='Contract')
    rate_snapshot_id = fields.Many2one('nbet.rate.snapshot', string='Rate Snapshot')

    # ── Quantities ────────────────────────────────────────────────────────────
    invoiced_capacity_mw = fields.Float(string='Invoiced Capacity (MW)', digits=(16, 4))
    invoiced_energy_kwh = fields.Float(string='Invoiced Energy (kWh)', digits=(16, 2))

    # ── Amounts ───────────────────────────────────────────────────────────────
    capacity_charge_amount = fields.Float(
        string='Capacity Charge', digits=(16, 2), tracking=True,
    )
    energy_charge_amount = fields.Float(
        string='Energy Charge', digits=(16, 2), tracking=True,
    )
    import_charge_amount = fields.Float(
        string='Import Liability Charge', digits=(16, 2), tracking=True,
    )
    adjustment_amount = fields.Float(
        string='Adjustments', digits=(16, 2), tracking=True,
    )
    total_expected_amount = fields.Float(
        string='Total Expected Amount', digits=(16, 2),
        compute='_compute_total', store=True, tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='billing_cycle_id.currency_id', store=True,
    )

    @api.depends(
        'capacity_charge_amount', 'energy_charge_amount',
        'import_charge_amount', 'adjustment_amount',
    )
    def _compute_total(self):
        for rec in self:
            rec.total_expected_amount = (
                rec.capacity_charge_amount
                + rec.energy_charge_amount
                + rec.import_charge_amount
                + rec.adjustment_amount
            )

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('computed', 'Computed'),
            ('reviewed', 'Reviewed'),
            ('approved', 'Approved'),
            ('posted', 'Posted'),
        ],
        default='draft', required=True, tracking=True,
    )
    compute_date = fields.Datetime(string='Computed On')
    version = fields.Integer(string='Version', default=1)
    notes = fields.Text(string='Notes')

    # ── Lines ─────────────────────────────────────────────────────────────────
    line_ids = fields.One2many(
        'nbet.genco.expected.bill.line', 'expected_bill_id', string='Bill Lines',
    )
    comparison_line_ids = fields.One2many(
        'nbet.genco.invoice.comparison.line', 'expected_bill_id', string='Comparison Lines',
    )

    # ── Vendor Bill Link ──────────────────────────────────────────────────────
    vendor_bill_id = fields.Many2one(
        'account.move', string='Vendor Bill', readonly=True,
        help='Odoo vendor bill created when the cycle is posted.',
    )

    # ── State Actions ─────────────────────────────────────────────────────────
    def action_review(self):
        self.write({'state': 'reviewed'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    def action_view_rate_snapshot(self):
        self.ensure_one()
        if not self.rate_snapshot_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.rate.snapshot',
            'res_id': self.rate_snapshot_id.id,
            'view_mode': 'form',
            'target': 'new',
        }


class NbetGencoExpectedBillLine(models.Model):
    _name = 'nbet.genco.expected.bill.line'
    _description = 'NBET GENCO Expected Bill Line'
    _order = 'expected_bill_id, sequence, id'

    expected_bill_id = fields.Many2one(
        'nbet.genco.expected.bill', string='Expected Bill',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        selection=[
            ('capacity', 'Capacity Charge'),
            ('energy', 'Energy Charge'),
            ('import', 'Import Liability'),
            ('adjustment', 'Adjustment'),
            ('penalty', 'Penalty'),
            ('other', 'Other'),
        ],
        string='Line Type', required=True,
    )
    description = fields.Char(string='Description')
    quantity = fields.Float(string='Quantity', digits=(16, 4))
    rate = fields.Float(string='Rate', digits=(16, 8))
    amount = fields.Float(
        string='Amount', digits=(16, 2),
        compute='_compute_amount', store=True,
    )
    amount_manual = fields.Float(
        string='Manual Amount', digits=(16, 2),
        help='Set this to override the computed amount.',
    )
    use_manual_amount = fields.Boolean(string='Override Amount', default=False)
    formula_trace = fields.Text(string='Formula Trace')
    currency_id = fields.Many2one(
        'res.currency', related='expected_bill_id.currency_id',
    )

    @api.depends('quantity', 'rate', 'amount_manual', 'use_manual_amount')
    def _compute_amount(self):
        for rec in self:
            if rec.use_manual_amount:
                rec.amount = rec.amount_manual
            else:
                rec.amount = rec.quantity * rec.rate
