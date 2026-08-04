# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

# Zero-padded: the selection is stored as text, so '01'..'12' keeps chronological
# order under the SQL sort used by _order and Group By ('9' would sort after '12').
MONTHS = [
    ('01', 'January'), ('02', 'February'), ('03', 'March'), ('04', 'April'),
    ('05', 'May'), ('06', 'June'), ('07', 'July'), ('08', 'August'),
    ('09', 'September'), ('10', 'October'), ('11', 'November'), ('12', 'December'),
]


class NisoAdvice(models.Model):
    _name = 'nbet.niso.advice'
    _description = 'NISO Admin Charge Advice'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_year desc, period_month desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Advice Number',
        required=True,
        readonly=True,
        default='New',
        copy=False,
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='NISO',
        required=True,
        default=lambda self: self._default_partner_id(),
        tracking=True,
        help='The Nigerian Independent System Operator, the party advising the charge '
             'and the debtor for it.',
    )
    advice_date = fields.Date(
        string='Advice Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help="Date NISO issued the advice. Used as the invoice date on the receivable.",
    )
    period_month = fields.Selection(
        MONTHS,
        string='Month',
        required=True,
        default=lambda self: '%02d' % fields.Date.context_today(self).month,
        tracking=True,
    )
    period_year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.context_today(self).year,
        tracking=True,
    )
    period_name = fields.Char(
        string='Period',
        compute='_compute_period_name',
        store=True,
        help='The month the admin charge relates to.',
    )
    niso_reference = fields.Char(
        string='NISO Reference',
        tracking=True,
        copy=False,
        help="NISO's own reference for the advice letter.",
    )

    amount_advised = fields.Monetary(
        string='Amount Advised',
        required=True,
        tracking=True,
        help='Admin charge NISO has advised for the period. This is the receivable raised '
             'on confirmation.',
    )
    amount_received = fields.Monetary(
        string='Amount Received',
        compute='_compute_amounts',
        store=True,
        tracking=True,
        help='Total of the posted receipts drawn down against this advice.',
    )
    amount_outstanding = fields.Monetary(
        string='Outstanding',
        compute='_compute_amounts',
        store=True,
        help='Advised less received: what NISO still owes on this advice.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('partial', 'Partially Received'),
        ('received', 'Fully Received'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)

    move_id = fields.Many2one(
        'account.move',
        string='Receivable Invoice',
        readonly=True,
        copy=False,
        help='Customer invoice raising the receivable against NISO for this advice.',
    )
    move_residual = fields.Monetary(
        related='move_id.amount_residual',
        string='Invoice Residual',
        help='Amount still open on the invoice in accounting. It should agree with the '
             'outstanding balance; a difference means the invoice was settled outside '
             'this module.',
    )
    receipt_ids = fields.One2many(
        'nbet.niso.receipt',
        'advice_id',
        string='Receipts',
    )
    receipt_count = fields.Integer(compute='_compute_receipt_count')
    note = fields.Text(string='Notes')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'The advice number must be unique.'),
        ('amount_advised_positive', 'CHECK(amount_advised >= 0)',
         'The amount advised cannot be negative.'),
    ]

    @api.model
    def _default_partner_id(self):
        param = self.env['ir.config_parameter'].sudo().get_param('nbet_niso.partner_id')
        if param:
            return self.env['res.partner'].browse(int(param)).exists()
        return False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.niso.advice') or 'New'
        return super().create(vals_list)

    @api.depends('period_month', 'period_year')
    def _compute_period_name(self):
        labels = dict(MONTHS)
        for rec in self:
            if rec.period_month and rec.period_year:
                rec.period_name = '%s %s' % (labels.get(rec.period_month, ''), rec.period_year)
            else:
                rec.period_name = ''

    @api.depends('amount_advised', 'receipt_ids.amount', 'receipt_ids.state')
    def _compute_amounts(self):
        for rec in self:
            received = sum(
                rec.receipt_ids.filtered(lambda r: r.state == 'posted').mapped('amount')
            )
            rec.amount_received = received
            rec.amount_outstanding = rec.amount_advised - received

    @api.depends('receipt_ids')
    def _compute_receipt_count(self):
        # Grouped read rather than len() per record, so the list view stays flat.
        counts = dict(self.env['nbet.niso.receipt']._read_group(
            [('advice_id', 'in', self.ids)], ['advice_id'], ['__count'],
        ))
        for rec in self:
            rec.receipt_count = counts.get(rec, 0)

    @api.constrains('period_month', 'period_year', 'partner_id', 'state')
    def _check_unique_period(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            duplicate = self.search([
                ('id', '!=', rec.id),
                ('partner_id', '=', rec.partner_id.id),
                ('period_month', '=', rec.period_month),
                ('period_year', '=', rec.period_year),
                ('state', '!=', 'cancelled'),
                ('company_id', '=', rec.company_id.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    "%s already advises the admin charge for %s (%s). Amend that advice "
                    "rather than raising a second one for the same month."
                    % (rec.partner_id.display_name, rec.period_name, duplicate.name)
                )

    @api.constrains('period_year')
    def _check_period_year(self):
        for rec in self:
            if not 2000 <= rec.period_year <= 2100:
                raise ValidationError("The advice year %s is not a valid period." % rec.period_year)

    # ------------------------------------------------------------------
    # Draw-down state
    # ------------------------------------------------------------------
    def _sync_receipt_state(self):
        """Move a confirmed advice through the draw-down states as receipts post."""
        for advice in self:
            if advice.state in ('draft', 'cancelled'):
                continue
            rounding = advice.currency_id.rounding
            if float_is_zero(advice.amount_received, precision_rounding=rounding):
                advice.state = 'confirmed'
            elif float_compare(
                advice.amount_received, advice.amount_advised, precision_rounding=rounding
            ) >= 0:
                advice.state = 'received'
            else:
                advice.state = 'partial'

    # ------------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------------
    def _get_income_account(self):
        self.ensure_one()
        param = self.env['ir.config_parameter'].sudo().get_param('nbet_niso.income_account_id')
        account = self.env['account.account'].browse(int(param)).exists() if param else False
        if not account:
            raise UserError(
                "No admin charge income account is configured, so the receivable for %s "
                "cannot be raised. Set it under Settings > Accounting > NBET NISO."
                % self.name
            )
        return account

    def _get_sale_journal(self):
        self.ensure_one()
        param = self.env['ir.config_parameter'].sudo().get_param('nbet_niso.sale_journal_id')
        journal = self.env['account.journal'].browse(int(param)).exists() if param else False
        if not journal:
            journal = self.env['account.journal'].sudo().search([
                ('type', '=', 'sale'),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
        if not journal:
            raise UserError(
                "No sales journal is configured, so the receivable for %s cannot be "
                "raised. Set one under Settings > Accounting > NBET NISO." % self.name
            )
        return journal

    def _prepare_invoice_vals(self):
        self.ensure_one()
        return {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': self.advice_date,
            'journal_id': self._get_sale_journal().id,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'invoice_origin': self.name,
            'ref': self.niso_reference or self.name,
            'invoice_line_ids': [(0, 0, {
                'name': 'NISO administrative charge - %s' % self.period_name,
                'quantity': 1.0,
                'price_unit': self.amount_advised,
                'account_id': self._get_income_account().id,
                # The advice is the agreed charge; no tax is computed on top of it.
                'tax_ids': [(5, 0, 0)],
            })],
        }

    def _create_invoice(self):
        self.ensure_one()
        move = self.env['account.move'].sudo().create(self._prepare_invoice_vals())
        move.action_post()
        return move

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(
                    "%s has already been confirmed and its receivable raised." % rec.name
                )
            if float_is_zero(rec.amount_advised, precision_rounding=rec.currency_id.rounding):
                raise UserError(
                    "Enter the amount NISO advised for %s before confirming it."
                    % rec.period_name
                )
            if not rec.partner_id.property_account_receivable_id:
                raise UserError(
                    "%s has no receivable account set, so the admin charge cannot be "
                    "booked against it." % rec.partner_id.display_name
                )
            rec.move_id = rec._create_invoice()
            rec.state = 'confirmed'
            rec.message_post(
                body="Advice confirmed by %s. Receivable of %s raised for %s on invoice %s."
                     % (self.env.user.display_name,
                        rec.currency_id.format(rec.amount_advised),
                        rec.period_name, rec.move_id.name)
            )

    def action_cancel(self):
        for rec in self:
            if any(r.state == 'posted' for r in rec.receipt_ids):
                raise UserError(
                    "%s has receipts posted against it and can no longer be cancelled. "
                    "Reverse the receipts in accounting first." % rec.name
                )
            if rec.move_id and rec.move_id.state == 'posted':
                rec.move_id.sudo().button_draft()
                rec.move_id.sudo().button_cancel()
            rec.receipt_ids.filtered(lambda r: r.state == 'draft').action_cancel()
            rec.state = 'cancelled'

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(
                    "Only a cancelled advice can be reset to draft. Cancel %s first."
                    % rec.name
                )
            rec.move_id = False
            rec.state = 'draft'

    def action_register_receipt(self):
        """Open a new receipt already drawn down against this advice."""
        self.ensure_one()
        if self.state not in ('confirmed', 'partial'):
            raise UserError(
                "Receipts can only be recorded against a confirmed advice that is not "
                "yet fully received. %s is %s."
                % (self.name, dict(self._fields['state'].selection)[self.state].lower())
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Register Receipt',
            'res_model': 'nbet.niso.receipt',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_advice_id': self.id,
                'default_amount': self.amount_outstanding,
            },
        }

    def action_view_receipts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Receipts',
            'res_model': 'nbet.niso.receipt',
            'view_mode': 'list,form',
            'domain': [('advice_id', '=', self.id)],
            'context': {'default_advice_id': self.id},
        }

    def action_view_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }
