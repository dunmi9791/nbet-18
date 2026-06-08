# -*- coding: utf-8 -*-
"""
NBET GENCO Invoice Submission and Comparison
Captures the invoice submitted by a GENCO and compares it line-by-line
against the system's expected bill.
"""
from odoo import models, fields, api
from odoo.exceptions import UserError


class NbetGencoInvoiceSubmission(models.Model):
    _name = 'nbet.genco.invoice.submission'
    _description = 'NBET GENCO Invoice Submission'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'billing_cycle_id desc, participant_id'

    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='cascade', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='GENCO',
        required=True, domain=[('participant_type', '=', 'genco')],
    )
    invoice_number = fields.Char(string='Invoice Number', tracking=True)
    invoice_date = fields.Date(string='Invoice Date', tracking=True)
    submitted_amount = fields.Float(
        string='Submitted Total (₦)', digits=(16, 2), tracking=True,
    )
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('under_review', 'Under Review'),
            ('matched', 'Matched'),
            ('variance', 'Variance Flagged'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('posted', 'Posted'),
        ],
        default='draft', required=True, tracking=True,
    )

    # ── Receipt Tracking ─────────────────────────────────────────────────────
    receipt_date = fields.Date(
        string='Receipt Date', tracking=True,
        help='Date the invoice was received by NBET.',
    )
    receipt_time = fields.Float(
        string='Receipt Time', tracking=True,
        help='Time the invoice was received (24h decimal, e.g. 14.5 = 2:30 PM).',
    )
    receipt_datetime = fields.Datetime(
        string='Received At', tracking=True,
        help='Exact date and time the invoice was received.',
    )
    delivery_method = fields.Selection(
        selection=[
            ('email', 'Email'),
            ('physical', 'Physical Delivery'),
            ('portal', 'Uploaded via Portal'),
        ],
        string='Delivery Method', tracking=True,
    )
    delivery_details = fields.Char(
        string='Delivery Details',
        help='Sender email address, courier name, or tracking number.',
    )
    received_by = fields.Many2one(
        'res.users', string='Received By',
        default=lambda self: self.env.user,
        tracking=True,
    )

    # ── Submitted Breakdown ──────────────────────────────────────────────────
    submitted_energy_kwh = fields.Float(
        string='Submitted Energy (kWh)', digits=(16, 2),
    )
    submitted_capacity_mw = fields.Float(
        string='Submitted Capacity (MW)', digits=(16, 4),
    )
    submitted_energy_charge = fields.Float(
        string='Submitted Energy Charge (₦)', digits=(16, 2),
    )
    submitted_capacity_charge = fields.Float(
        string='Submitted Capacity Charge (₦)', digits=(16, 2),
    )
    submitted_startup_cost = fields.Float(
        string='Submitted Startup Cost (₦)', digits=(16, 2),
    )
    submitted_other_charges = fields.Float(
        string='Submitted Other Charges (₦)', digits=(16, 2),
    )

    # ── Comparison & Workflow ────────────────────────────────────────────────
    expected_bill_id = fields.Many2one(
        'nbet.genco.expected.bill', string='Expected Bill',
        domain="[('billing_cycle_id','=',billing_cycle_id),('participant_id','=',participant_id)]",
    )
    variance_amount = fields.Float(
        string='Variance Amount', digits=(16, 2),
        compute='_compute_variance', store=True, tracking=True,
    )
    variance_percent = fields.Float(
        string='Variance (%)', digits=(5, 4),
        compute='_compute_variance', store=True,
    )
    is_within_tolerance = fields.Boolean(
        string='Within Tolerance', compute='_compute_variance', store=True,
    )
    tolerance_percent = fields.Float(
        string='Tolerance (%)', default=1.0,
        help='Variance within this % is auto-matched. Configurable per submission.',
    )
    review_notes = fields.Text(string='Review Notes')
    reviewed_by = fields.Many2one('res.users', string='Reviewed By', tracking=True)
    reviewed_date = fields.Datetime(string='Reviewed On', tracking=True)
    comparison_line_ids = fields.One2many(
        'nbet.genco.invoice.comparison.line', 'submission_id', string='Comparison Lines',
    )
    currency_id = fields.Many2one(
        'res.currency', related='billing_cycle_id.currency_id',
    )
    vendor_bill_id = fields.Many2one(
        'account.move', string='Vendor Bill', readonly=True,
        help='Odoo vendor bill created when this submission is posted.',
    )

    @api.depends('submitted_amount', 'expected_bill_id', 'expected_bill_id.total_expected_amount', 'tolerance_percent')
    def _compute_variance(self):
        for rec in self:
            expected = rec.expected_bill_id.total_expected_amount if rec.expected_bill_id else 0.0
            rec.variance_amount = rec.submitted_amount - expected
            if expected:
                rec.variance_percent = abs(rec.variance_amount) / expected * 100.0
            else:
                rec.variance_percent = 0.0
            rec.is_within_tolerance = rec.variance_percent <= rec.tolerance_percent

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Only draft submissions can be submitted.')
            if not rec.receipt_datetime:
                rec.receipt_datetime = fields.Datetime.now()
            if not rec.receipt_date:
                rec.receipt_date = fields.Date.today()
            if not rec.received_by:
                rec.received_by = self.env.user
            rec.state = 'submitted'
            rec.message_post(
                body=f'Invoice {rec.invoice_number} submitted for review. '
                     f'Received on {rec.receipt_date} via {rec.delivery_method or "unspecified"}.'
            )

    def action_compare(self):
        """Run comparison against expected bill and populate comparison lines."""
        for rec in self:
            if not rec.expected_bill_id:
                raise UserError('Please link an expected bill before comparing.')
            rec.comparison_line_ids.unlink()

            submitted_map = {
                'capacity': rec.submitted_capacity_charge,
                'energy': rec.submitted_energy_charge,
            }

            lines_to_create = []
            for exp_line in rec.expected_bill_id.line_ids:
                submitted_amt = submitted_map.get(exp_line.line_type, 0.0)
                lines_to_create.append({
                    'submission_id': rec.id,
                    'expected_bill_id': rec.expected_bill_id.id,
                    'expected_bill_line_id': exp_line.id,
                    'submitted_component_name': exp_line.description or exp_line.line_type,
                    'expected_amount': exp_line.amount,
                    'submitted_amount': submitted_amt,
                    'currency_id': rec.currency_id.id,
                })
            if lines_to_create:
                self.env['nbet.genco.invoice.comparison.line'].create(lines_to_create)
            if rec.is_within_tolerance:
                rec.state = 'matched'
            else:
                rec.state = 'variance'
            rec.message_post(
                body=f'Comparison run. Variance: ₦{rec.variance_amount:,.2f} ({rec.variance_percent:.2f}%). '
                     f'Status: {"Matched" if rec.is_within_tolerance else "Variance Flagged"}.'
            )

    def action_approve(self):
        for rec in self:
            rec.write({
                'state': 'approved',
                'reviewed_by': self.env.user.id,
                'reviewed_date': fields.Datetime.now(),
            })
            rec.message_post(body=f'Invoice approved by {self.env.user.name}.')

    def action_reject(self):
        for rec in self:
            rec.write({
                'state': 'rejected',
                'reviewed_by': self.env.user.id,
                'reviewed_date': fields.Datetime.now(),
            })
            rec.message_post(body=f'Invoice rejected by {self.env.user.name}.')

    def action_under_review(self):
        self.write({'state': 'under_review'})

    def action_post(self):
        """Create a vendor bill from this approved submission via the accounting service."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError('Only approved submissions can be posted.')
            if not rec.expected_bill_id:
                raise UserError('No expected bill linked. Cannot post without an expected bill.')
            if rec.vendor_bill_id:
                raise UserError(f'Already posted as {rec.vendor_bill_id.name}.')

            svc = self.env['nbet.accounting.service']
            move = svc.create_genco_vendor_bill(rec.expected_bill_id)
            if not move:
                raise UserError(
                    'Could not create vendor bill. Check that the GENCO has a linked '
                    'partner and accounting accounts are configured.'
                )
            rec.vendor_bill_id = move.id
            rec.expected_bill_id.vendor_bill_id = move.id
            rec.expected_bill_id.state = 'posted'
            rec.state = 'posted'
            rec.message_post(
                body=f'Posted to journal as vendor bill <a href="/web#id={move.id}&model=account.move">'
                     f'{move.name}</a>. Invoice received on {rec.receipt_date} via {rec.delivery_method or "N/A"}.'
            )

    def action_view_vendor_bill(self):
        self.ensure_one()
        if not self.vendor_bill_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.vendor_bill_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class NbetGencoInvoiceComparisonLine(models.Model):
    _name = 'nbet.genco.invoice.comparison.line'
    _description = 'NBET GENCO Invoice Comparison Line'
    _order = 'submission_id, id'

    submission_id = fields.Many2one(
        'nbet.genco.invoice.submission', string='Submission',
        required=True, ondelete='cascade', index=True,
    )
    expected_bill_id = fields.Many2one('nbet.genco.expected.bill', string='Expected Bill')
    expected_bill_line_id = fields.Many2one(
        'nbet.genco.expected.bill.line', string='Expected Bill Line',
    )
    submitted_component_name = fields.Char(string='Submitted Component')
    expected_amount = fields.Float(string='Expected Amount', digits=(16, 2))
    submitted_amount = fields.Float(string='Submitted Amount', digits=(16, 2))
    variance_amount = fields.Float(
        string='Variance', digits=(16, 2),
        compute='_compute_variance', store=True,
    )
    variance_percent = fields.Float(
        string='Variance (%)', digits=(5, 4),
        compute='_compute_variance', store=True,
    )
    status = fields.Selection(
        selection=[
            ('matched', 'Matched'),
            ('under', 'Under-billed'),
            ('over', 'Over-billed'),
            ('missing', 'Missing (not in submission)'),
            ('extra', 'Extra (not in expected bill)'),
        ],
        compute='_compute_variance', store=True,
    )
    currency_id = fields.Many2one('res.currency')
    notes = fields.Char(string='Notes')

    @api.depends('expected_amount', 'submitted_amount')
    def _compute_variance(self):
        MATCH_THRESHOLD = 1.0  # percent
        for rec in self:
            rec.variance_amount = rec.submitted_amount - rec.expected_amount
            if rec.expected_amount:
                rec.variance_percent = abs(rec.variance_amount) / rec.expected_amount * 100.0
            else:
                rec.variance_percent = 0.0

            if rec.expected_amount == 0 and rec.submitted_amount > 0:
                rec.status = 'extra'
            elif rec.submitted_amount == 0 and rec.expected_amount > 0:
                rec.status = 'missing'
            elif abs(rec.variance_percent) <= MATCH_THRESHOLD:
                rec.status = 'matched'
            elif rec.submitted_amount < rec.expected_amount:
                rec.status = 'under'
            else:
                rec.status = 'over'
