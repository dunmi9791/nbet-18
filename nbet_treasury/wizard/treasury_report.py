# -*- coding: utf-8 -*-
from datetime import datetime

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class TreasuryReport(models.TransientModel):
    """Balances and cash movements of every active bank account, broken down
    per day, week or month over the requested period."""
    _name = 'nbet.treasury.report'
    _description = 'Treasury Report'

    def _default_date_from(self):
        return fields.Date.context_today(self).replace(day=1)

    date_from = fields.Date(
        string='From',
        required=True,
        default=_default_date_from,
    )
    date_to = fields.Date(
        string='To',
        required=True,
        default=fields.Date.context_today,
    )
    period_type = fields.Selection([
        ('day', 'Day'),
        ('week', 'Week'),
        ('month', 'Month'),
    ], string='Break Down By', default='month', required=True,
        help='Granularity of the inflow / outflow summary for each bank account.')

    journal_ids = fields.Many2many(
        'account.journal',
        string='Bank Accounts',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        help='Leave empty to report on every active bank account of the company.',
    )
    include_cash = fields.Boolean(
        string='Include Cash Accounts',
        default=False,
        help='Also report on cash journals, not only bank journals.',
    )
    target_move = fields.Selection([
        ('posted', 'Posted Entries Only'),
        ('all', 'All Entries (incl. Draft)'),
    ], string='Entries', default='posted', required=True)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        string='Company Currency',
    )

    line_ids = fields.One2many(
        'nbet.treasury.report.line', 'report_id', string='Bank Account Balances',
    )
    period_line_ids = fields.One2many(
        'nbet.treasury.report.period', 'report_id', string='Period Breakdown',
    )
    generated_on = fields.Datetime(string='Generated On', readonly=True)

    total_opening = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    total_inflow = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    total_outflow = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    total_net = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    total_closing = fields.Monetary(compute='_compute_totals', currency_field='currency_id')

    @api.depends('line_ids.opening_balance', 'line_ids.inflow',
                 'line_ids.outflow', 'line_ids.closing_balance')
    def _compute_totals(self):
        for report in self:
            lines = report.line_ids
            report.total_opening = sum(lines.mapped('opening_balance'))
            report.total_inflow = sum(lines.mapped('inflow'))
            report.total_outflow = sum(lines.mapped('outflow'))
            report.total_net = report.total_inflow - report.total_outflow
            report.total_closing = sum(lines.mapped('closing_balance'))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for report in self:
            if report.date_from > report.date_to:
                raise UserError(_('The start date must be earlier than the end date.'))

    # ------------------------------------------------------------------
    # Period helpers
    # ------------------------------------------------------------------
    def _period_start(self, day):
        """Return the first day of the period ``day`` belongs to."""
        self.ensure_one()
        if self.period_type == 'day':
            return day
        if self.period_type == 'week':
            return day - relativedelta(days=day.weekday())
        return day.replace(day=1)

    def _period_stop(self, start):
        """Return the last day of the period starting on ``start``."""
        self.ensure_one()
        if self.period_type == 'day':
            return start
        if self.period_type == 'week':
            return start + relativedelta(days=6)
        return start + relativedelta(months=1, days=-1)

    def _period_label(self, natural_start, start, stop):
        """Name the bucket after its calendar period, but show the days it
        actually covers: a first or last bucket clipped by the date range must
        not advertise movements it does not contain."""
        self.ensure_one()
        if self.period_type == 'day':
            return format_date(self.env, start)
        if self.period_type == 'week':
            return _('Week %(week)s, %(year)s (%(start)s - %(stop)s)',
                     week=natural_start.isocalendar()[1],
                     year=natural_start.isocalendar()[0],
                     start=format_date(self.env, start), stop=format_date(self.env, stop))
        label = format_date(self.env, natural_start, date_format='MMMM yyyy')
        if start != natural_start or stop != self._period_stop(natural_start):
            label = _('%(month)s (%(start)s - %(stop)s)', month=label,
                      start=format_date(self.env, start), stop=format_date(self.env, stop))
        return label

    def _iter_periods(self):
        """Yield ``(start, stop, label)`` for every period in the range, in order.

        Period bounds are clamped to the requested date range so the first and
        last buckets never claim movements outside of it.
        """
        self.ensure_one()
        cursor = self._period_start(self.date_from)
        while cursor <= self.date_to:
            natural_stop = self._period_stop(cursor)
            start = max(cursor, self.date_from)
            stop = min(natural_stop, self.date_to)
            yield (start, stop, self._period_label(cursor, start, stop))
            cursor = natural_stop + relativedelta(days=1)

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------
    def _get_journals(self):
        """Active bank (and optionally cash) journals to report on."""
        self.ensure_one()
        if self.journal_ids:
            return self.journal_ids.filtered(lambda j: j.company_id == self.company_id)
        journal_types = ['bank'] + (['cash'] if self.include_cash else [])
        return self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('type', 'in', journal_types),
        ], order='name')

    def _journals_by_account(self):
        """Map each bank GL account to the single journal reporting on it.

        Two journals sharing a default account would otherwise double count the
        same ledger, so the first one wins.
        """
        self.ensure_one()
        mapping = {}
        for journal in self._get_journals():
            account = journal.default_account_id
            if account and account.id not in mapping:
                mapping[account.id] = journal
        return mapping

    def _move_line_domain(self, account_ids):
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('account_id', 'in', account_ids),
            ('display_type', 'not in', ('line_section', 'line_note')),
        ]
        if self.target_move == 'posted':
            domain.append(('parent_state', '=', 'posted'))
        else:
            domain.append(('parent_state', 'in', ('draft', 'posted')))
        return domain

    def action_generate(self):
        """(Re)build the report lines and open them full screen."""
        self.ensure_one()
        if self.company_id not in self.env.companies:
            raise UserError(_('You are not allowed to report on company %s.', self.company_id.display_name))
        self._check_dates()

        self.line_ids.unlink()
        self.period_line_ids.unlink()
        self._build_lines()
        self.generated_on = fields.Datetime.now()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Treasury Report'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('nbet_treasury.view_treasury_report_result').id,
            'target': 'current',
        }

    def _build_lines(self):
        """Aggregate the bank ledgers once, then fan the figures out into the
        balance lines and the per-period breakdown."""
        self.ensure_one()
        journal_by_account = self._journals_by_account()
        if not journal_by_account:
            raise UserError(_(
                'No active bank account was found for %s. Bank journals need a '
                'default account before they can be reported on.',
                self.company_id.display_name))

        account_ids = list(journal_by_account)
        # Bank ledgers are read with elevated rights: treasury staff are meant to
        # see these balances without being granted read access on every journal
        # item in the database. The company is pinned in the domain instead.
        AML = self.env['account.move.line'].sudo()
        base_domain = self._move_line_domain(account_ids)

        opening = {
            account.id: balance
            for account, balance in AML._read_group(
                base_domain + [('date', '<', self.date_from)],
                groupby=['account_id'],
                aggregates=['balance:sum'],
            )
        }

        period_domain = base_domain + [
            ('date', '>=', self.date_from), ('date', '<=', self.date_to),
        ]
        inflow_rows = AML._read_group(
            period_domain + [('debit', '>', 0)],
            groupby=['account_id', 'date:day'],
            aggregates=['debit:sum', '__count'],
        )
        outflow_rows = AML._read_group(
            period_domain + [('credit', '>', 0)],
            groupby=['account_id', 'date:day'],
            aggregates=['credit:sum', '__count'],
        )

        # {account_id: {period_start: [inflow, outflow, moves]}}
        buckets = {account_id: {} for account_id in account_ids}
        for rows, slot in ((inflow_rows, 0), (outflow_rows, 1)):
            for account, day, amount, count in rows:
                key = self._period_start(self._as_date(day))
                bucket = buckets[account.id].setdefault(key, [0.0, 0.0, 0])
                bucket[slot] += amount
                bucket[2] += count

        periods = list(self._iter_periods())
        line_vals, period_vals = [], []
        for account_id, journal in journal_by_account.items():
            running = opening.get(account_id, 0.0)
            line_opening = running
            total_in = total_out = total_moves = 0
            for sequence, (start, stop, label) in enumerate(periods, start=1):
                inflow, outflow, moves = buckets[account_id].get(
                    self._period_start(start), [0.0, 0.0, 0])
                closing = running + inflow - outflow
                period_vals.append({
                    'report_id': self.id,
                    'sequence': sequence,
                    'journal_id': journal.id,
                    'period_label': label,
                    'date_start': start,
                    'date_stop': stop,
                    'opening_balance': running,
                    'inflow': inflow,
                    'outflow': outflow,
                    'closing_balance': closing,
                    'move_count': moves,
                })
                running = closing
                total_in += inflow
                total_out += outflow
                total_moves += moves

            line_vals.append({
                'report_id': self.id,
                'journal_id': journal.id,
                'account_id': account_id,
                'opening_balance': line_opening,
                'inflow': total_in,
                'outflow': total_out,
                'closing_balance': running,
                'move_count': total_moves,
            })

        self.env['nbet.treasury.report.line'].create(line_vals)
        self.env['nbet.treasury.report.period'].create(period_vals)

    @staticmethod
    def _as_date(value):
        """``_read_group`` may hand back a datetime for a date granularity."""
        return value.date() if isinstance(value, datetime) else value

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_print_pdf(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Generate the report before printing it.'))
        return self.env.ref('nbet_treasury.action_report_treasury').report_action(self)

    def action_back_to_filters(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Treasury Report'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('nbet_treasury.view_treasury_report_wizard').id,
            'target': 'new',
        }


class TreasuryReportLine(models.TransientModel):
    _name = 'nbet.treasury.report.line'
    _description = 'Treasury Report - Bank Account Balance'
    _order = 'journal_name, id'

    report_id = fields.Many2one(
        'nbet.treasury.report', required=True, ondelete='cascade', index=True,
    )
    journal_id = fields.Many2one('account.journal', string='Bank Account', required=True)
    journal_name = fields.Char(related='journal_id.name', string='Journal', store=True)
    journal_code = fields.Char(related='journal_id.code', string='Code')
    account_id = fields.Many2one('account.account', string='GL Account')
    bank_id = fields.Many2one(related='journal_id.bank_account_id.bank_id', string='Bank')
    acc_number = fields.Char(related='journal_id.bank_account_id.acc_number', string='Account Number')
    journal_currency_id = fields.Many2one(related='journal_id.currency_id', string='Journal Currency')
    currency_id = fields.Many2one(related='report_id.currency_id')

    opening_balance = fields.Monetary(string='Opening Balance', currency_field='currency_id')
    inflow = fields.Monetary(string='Inflow', currency_field='currency_id')
    outflow = fields.Monetary(string='Outflow', currency_field='currency_id')
    net_movement = fields.Monetary(
        string='Net Movement', currency_field='currency_id',
        compute='_compute_net_movement', store=True,
    )
    closing_balance = fields.Monetary(string='Closing Balance', currency_field='currency_id')
    move_count = fields.Integer(string='Transactions')

    @api.depends('inflow', 'outflow')
    def _compute_net_movement(self):
        for line in self:
            line.net_movement = line.inflow - line.outflow

    def action_open_move_lines(self):
        """Drill down to the journal items behind the figures on this line."""
        self.ensure_one()
        report = self.report_id
        domain = report._move_line_domain([self.account_id.id]) + [
            ('date', '>=', report.date_from), ('date', '<=', report.date_to),
        ]
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s - Journal Items', self.journal_id.name),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': domain,
        }


class TreasuryReportPeriod(models.TransientModel):
    _name = 'nbet.treasury.report.period'
    _description = 'Treasury Report - Period Movement'
    _order = 'journal_name, sequence, id'

    report_id = fields.Many2one(
        'nbet.treasury.report', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=1)
    journal_id = fields.Many2one('account.journal', string='Bank Account', required=True)
    journal_name = fields.Char(related='journal_id.name', string='Journal', store=True)
    period_label = fields.Char(string='Period', required=True)
    date_start = fields.Date(string='Period Start')
    date_stop = fields.Date(string='Period End')
    currency_id = fields.Many2one(related='report_id.currency_id')

    opening_balance = fields.Monetary(string='Opening Balance', currency_field='currency_id')
    inflow = fields.Monetary(string='Inflow', currency_field='currency_id')
    outflow = fields.Monetary(string='Outflow', currency_field='currency_id')
    net_movement = fields.Monetary(
        string='Net Movement', currency_field='currency_id',
        compute='_compute_net_movement', store=True,
    )
    closing_balance = fields.Monetary(string='Closing Balance', currency_field='currency_id')
    move_count = fields.Integer(string='Transactions')

    @api.depends('inflow', 'outflow')
    def _compute_net_movement(self):
        for period in self:
            period.net_movement = period.inflow - period.outflow

    def action_open_move_lines(self):
        self.ensure_one()
        report = self.report_id
        domain = report._move_line_domain([self.journal_id.default_account_id.id]) + [
            ('date', '>=', self.date_start), ('date', '<=', self.date_stop),
        ]
        return {
            'type': 'ir.actions.act_window',
            'name': _('%(journal)s - %(period)s',
                      journal=self.journal_id.name, period=self.period_label),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': domain,
        }
