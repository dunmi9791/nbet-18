# -*- coding: utf-8 -*-
"""
NBET DISCO Bill
The customer invoice basis for a DISCO for a billing cycle.
Applied DRO % is frozen at computation time and never modified retroactively.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class NbetDiscoBill(models.Model):
    _name = 'nbet.disco.bill'
    _description = 'NBET DISCO Monthly Bill'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'billing_cycle_id desc, participant_id'

    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='cascade', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='DISCO',
        required=True, domain=[('participant_type', '=', 'disco')],
        ondelete='restrict', tracking=True,
    )
    capacity_delivered_mw = fields.Float(string='Capacity Delivered (MW)', digits=(16, 4))
    energy_delivered_kwh = fields.Float(string='Energy Delivered (kWh)', digits=(16, 2))

    # ── Amounts ───────────────────────────────────────────────────────────────
    gross_bill_amount = fields.Float(
        string='Gross Bill Amount', digits=(16, 2),
        compute='_compute_gross', store=True, tracking=True,
    )
    applied_dro_id = fields.Many2one(
        'nbet.disco.dro', string='Applied DRO Record', tracking=True,
    )
    applied_dro_percent = fields.Float(
        string='Applied DRO (%)', digits=(5, 2), tracking=True,
        help='DRO % frozen at computation time.',
    )
    expected_payable_amount = fields.Float(
        string='Expected Payable', digits=(16, 2),
        compute='_compute_payable', store=True, tracking=True,
    )
    subsidy_amount = fields.Float(
        string='Subsidy Amount', digits=(16, 2),
        compute='_compute_payable', store=True, tracking=True,
    )
    grant_amount = fields.Float(
        string='Grant Amount', digits=(16, 2), tracking=True,
        help='Grant separately tracked from subsidy if applicable.',
    )
    adjustment_amount = fields.Float(
        string='Adjustments', digits=(16, 2), tracking=True,
    )
    total_invoice_amount = fields.Float(
        string='Total Invoice Amount', digits=(16, 2),
        compute='_compute_total', store=True, tracking=True,
        help='The amount actually invoiced to the DISCO (DRO portion + adjustments).',
    )
    currency_id = fields.Many2one(
        'res.currency', related='billing_cycle_id.currency_id', store=True,
    )

    @api.depends('line_ids', 'line_ids.amount', 'line_ids.is_subsidy_line')
    def _compute_gross(self):
        for rec in self:
            rec.gross_bill_amount = sum(
                l.amount for l in rec.line_ids if not l.is_subsidy_line
            )

    @api.depends('gross_bill_amount', 'applied_dro_percent', 'grant_amount')
    def _compute_payable(self):
        for rec in self:
            rec.expected_payable_amount = rec.gross_bill_amount * rec.applied_dro_percent / 100.0
            rec.subsidy_amount = rec.gross_bill_amount - rec.expected_payable_amount - rec.grant_amount

    @api.depends('expected_payable_amount', 'adjustment_amount')
    def _compute_total(self):
        for rec in self:
            rec.total_invoice_amount = rec.expected_payable_amount + rec.adjustment_amount

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('computed', 'Computed'),
            ('reviewed', 'Reviewed'),
            ('approved', 'Approved'),
            ('invoiced', 'Invoiced'),
            ('paid', 'Paid'),
            ('partial', 'Partially Paid'),
        ],
        default='draft', required=True, tracking=True,
    )
    invoice_move_id = fields.Many2one(
        'account.move', string='Customer Invoice', readonly=True,
    )
    notes = fields.Text(string='Notes')
    compute_date = fields.Datetime(string='Computed On')
    company_id = fields.Many2one(
        'res.company', related='billing_cycle_id.company_id', store=True,
    )

    # ── Lines ─────────────────────────────────────────────────────────────────
    line_ids = fields.One2many(
        'nbet.disco.bill.line', 'disco_bill_id', string='Bill Lines',
    )

    # ── Constraints ────────────────────────────────────────────────────────────
    _sql_constraints = [
        ('cycle_participant_uniq', 'unique(billing_cycle_id, participant_id)',
         'Only one DISCO bill per DISCO per billing cycle is allowed.'),
    ]

    @api.constrains('participant_id')
    def _check_is_disco(self):
        for rec in self:
            if rec.participant_id and rec.participant_id.participant_type != 'disco':
                raise ValidationError(
                    f'{rec.participant_id.name} is not a DISCO.'
                )

    # ── Actions ────────────────────────────────────────────────────────────────
    def action_review(self):
        self.write({'state': 'reviewed'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_create_invoice(self):
        """Create Odoo customer invoice for this DISCO bill."""
        self.ensure_one()
        if self.invoice_move_id:
            return self.action_view_invoice()
        acct_svc = self.env['nbet.accounting.service'].create({})
        acct_svc.create_disco_customer_invoice(self)
        self.state = 'invoiced'
        return self.action_view_invoice()

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_move_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_move_id.id,
            'view_mode': 'form',
        }


class NbetDiscoBillLine(models.Model):
    _name = 'nbet.disco.bill.line'
    _description = 'NBET DISCO Bill Line'
    _order = 'disco_bill_id, sequence, id'

    disco_bill_id = fields.Many2one(
        'nbet.disco.bill', string='DISCO Bill',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        selection=[
            ('capacity', 'Capacity Charge'),
            ('energy', 'Energy Charge'),
            ('adjustment', 'Adjustment'),
            ('prior_balance', 'Prior Period Balance'),
            ('subsidy', 'Subsidy Offset'),
            ('grant', 'Grant'),
            ('other', 'Other'),
        ],
        string='Line Type', required=True,
    )
    description = fields.Char(string='Description')
    quantity = fields.Float(string='Quantity', digits=(16, 4))
    rate = fields.Float(string='Rate', digits=(16, 8))
    amount = fields.Float(string='Amount', digits=(16, 2))
    is_subsidy_line = fields.Boolean(
        string='Subsidy Line', default=False,
        help='Marks lines representing subsidy exposure (excluded from gross bill).',
    )
    currency_id = fields.Many2one(
        'res.currency', related='disco_bill_id.currency_id',
    )
