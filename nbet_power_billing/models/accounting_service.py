# -*- coding: utf-8 -*-
"""
NBET Accounting Service
Creates Odoo accounting documents (account.move) from approved billing records.
All moves carry references back to the billing cycle and participant.
"""
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class NbetAccountingService(models.TransientModel):
    _name = 'nbet.accounting.service'
    _description = 'NBET Accounting Service'

    # ──────────────────────────────────────────────────────────────────────────
    # Main Entry Point
    # ──────────────────────────────────────────────────────────────────────────

    def post_cycle_accounting(self, cycle):
        """Create all accounting documents for an approved billing cycle.

        1. Vendor bills for approved GENCO expected bills
        2. Customer invoices for approved DISCO bills
        3. Journal entries for approved adjustments
        4. Auto-post if configured

        Returns:
            list: IDs of created account.move records
        """
        cfg = self.env['nbet.billing.config'].get_config(cycle.company_id)
        created_moves = []

        # GENCO vendor bills
        for bill in cycle.expected_bill_ids.filtered(lambda b: b.state == 'approved'):
            move = self.create_genco_vendor_bill(bill, cfg)
            if move:
                bill.vendor_bill_id = move.id
                bill.state = 'posted'
                created_moves.append(move.id)

        # DISCO customer invoices
        for disco_bill in cycle.disco_bill_ids.filtered(lambda b: b.state == 'approved'):
            moves = self.create_disco_customer_invoice(disco_bill, cfg)
            if moves:
                disco_bill.invoice_move_id = moves[0].id
                disco_bill.state = 'invoiced'
                created_moves.extend([m.id for m in moves])

        # Adjustments
        for adj in cycle.adjustment_ids.filtered(lambda a: a.approval_state == 'approved' and not a.journal_entry_id):
            move = self.create_adjustment_entry(adj, cfg)
            if move:
                adj.journal_entry_id = move.id
                created_moves.append(move.id)

        # Auto-post
        if cfg.auto_post_invoices and created_moves:
            moves = self.env['account.move'].browse(created_moves)
            moves_to_post = moves.filtered(lambda m: m.state == 'draft')
            moves_to_post.action_post()

        _logger.info('Cycle %s: created %d accounting documents.', cycle.name, len(created_moves))
        return created_moves

    # ──────────────────────────────────────────────────────────────────────────
    # GENCO Vendor Bill
    # ──────────────────────────────────────────────────────────────────────────

    def create_genco_vendor_bill(self, expected_bill, cfg=None):
        """Create a vendor bill (in_invoice) for an approved GENCO expected bill."""
        if not expected_bill.participant_id.partner_id:
            _logger.warning(
                'GENCO %s has no linked Odoo partner; skipping vendor bill.',
                expected_bill.participant_id.name,
            )
            return False

        if cfg is None:
            cfg = self.env['nbet.billing.config'].get_config()

        cycle = expected_bill.billing_cycle_id
        partner = expected_bill.participant_id.partner_id
        journal = cfg.payable_journal_id or self.env['account.journal'].search(
            [('type', '=', 'purchase'), ('company_id', '=', cycle.company_id.id)], limit=1
        )

        invoice_lines = self._build_genco_invoice_lines(expected_bill, cfg)
        if not invoice_lines:
            return False

        narration = (
            f'NBET Settlement — {cycle.name}\n'
            f'Participant: {expected_bill.participant_id.name}\n'
            f'Billing Cycle: {cycle.code}\n'
            f'Expected Bill ID: {expected_bill.id}'
        )

        move_vals = {
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': cycle.invoice_date or fields.Date.today(),
            'journal_id': journal.id,
            'ref': f'NBET/{cycle.code}/{expected_bill.participant_id.code}',
            'narration': narration,
            'company_id': cycle.company_id.id,
            'currency_id': expected_bill.currency_id.id,
            'invoice_line_ids': [(0, 0, line) for line in invoice_lines],
        }
        return self.env['account.move'].create(move_vals)

    def _build_genco_invoice_lines(self, expected_bill, cfg):
        """Build invoice line dicts for a GENCO expected bill."""
        lines = []
        for bl in expected_bill.line_ids:
            account = self._get_account_for_line_type(bl.line_type, 'genco', cfg)
            if not account:
                _logger.warning(
                    'No account configured for line type %s (GENCO); skipping line.',
                    bl.line_type,
                )
                continue
            lines.append({
                'name': bl.description or bl.line_type,
                'quantity': 1.0,
                'price_unit': bl.amount,
                'account_id': account.id,
            })
        return lines

    # ──────────────────────────────────────────────────────────────────────────
    # DISCO Customer Invoice
    # ──────────────────────────────────────────────────────────────────────────

    def create_disco_customer_invoice(self, disco_bill, cfg=None):
        """Create customer invoice(s) for a DISCO bill based on configured invoice mode.

        Returns:
            list of account.move records created
        """
        if not disco_bill.participant_id.partner_id:
            _logger.warning(
                'DISCO %s has no linked Odoo partner; skipping invoice.',
                disco_bill.participant_id.name,
            )
            return []

        if cfg is None:
            cfg = self.env['nbet.billing.config'].get_config()

        mode = cfg.disco_invoice_mode
        created = []

        if mode == 'dro_only':
            move = self._create_disco_invoice_dro_only(disco_bill, cfg)
            if move:
                created.append(move)

        elif mode == 'full_with_credit':
            invoice = self._create_disco_invoice_full(disco_bill, cfg)
            if invoice:
                created.append(invoice)
            if disco_bill.subsidy_amount > 0:
                credit_note = self._create_subsidy_credit_note(disco_bill, cfg)
                if credit_note:
                    created.append(credit_note)

        elif mode == 'dro_plus_subsidy_receivable':
            invoice = self._create_disco_invoice_dro_only(disco_bill, cfg)
            if invoice:
                created.append(invoice)
            if disco_bill.subsidy_amount > 0:
                je = self._create_subsidy_receivable_entry(disco_bill, cfg)
                if je:
                    created.append(je)

        return created

    def _create_disco_invoice_dro_only(self, disco_bill, cfg):
        """Invoice DISCO for DRO portion only."""
        cycle = disco_bill.billing_cycle_id
        journal = cfg.receivable_journal_id or self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', cycle.company_id.id)], limit=1
        )
        lines = self._build_disco_invoice_lines(disco_bill, cfg, include_subsidy=False)
        if not lines:
            return False

        narration = (
            f'NBET DISCO Invoice — {cycle.name}\n'
            f'DRO Applied: {disco_bill.applied_dro_percent:.2f}%\n'
            f'Billing Cycle: {cycle.code}'
        )
        move_vals = {
            'move_type': 'out_invoice',
            'partner_id': disco_bill.participant_id.partner_id.id,
            'invoice_date': cycle.invoice_date or fields.Date.today(),
            'journal_id': journal.id,
            'ref': f'NBET/{cycle.code}/{disco_bill.participant_id.code}',
            'narration': narration,
            'company_id': cycle.company_id.id,
            'currency_id': disco_bill.currency_id.id,
            'invoice_line_ids': [(0, 0, line) for line in lines],
        }
        return self.env['account.move'].create(move_vals)

    def _create_disco_invoice_full(self, disco_bill, cfg):
        """Invoice DISCO for the full gross amount."""
        cycle = disco_bill.billing_cycle_id
        journal = cfg.receivable_journal_id or self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', cycle.company_id.id)], limit=1
        )
        lines = self._build_disco_invoice_lines(disco_bill, cfg, include_subsidy=True)
        if not lines:
            return False

        move_vals = {
            'move_type': 'out_invoice',
            'partner_id': disco_bill.participant_id.partner_id.id,
            'invoice_date': cycle.invoice_date or fields.Date.today(),
            'journal_id': journal.id,
            'ref': f'NBET/{cycle.code}/{disco_bill.participant_id.code}-FULL',
            'narration': f'NBET DISCO Full Invoice — {cycle.name}',
            'company_id': cycle.company_id.id,
            'currency_id': disco_bill.currency_id.id,
            'invoice_line_ids': [(0, 0, line) for line in lines],
        }
        return self.env['account.move'].create(move_vals)

    def _create_subsidy_credit_note(self, disco_bill, cfg):
        """Create a credit note for the subsidy amount on the DISCO's invoice."""
        cycle = disco_bill.billing_cycle_id
        journal = cfg.receivable_journal_id or self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', cycle.company_id.id)], limit=1
        )
        account = cfg.subsidy_receivable_account_id
        if not account:
            _logger.warning('No subsidy receivable account configured; skipping credit note.')
            return False

        move_vals = {
            'move_type': 'out_refund',
            'partner_id': disco_bill.participant_id.partner_id.id,
            'invoice_date': cycle.invoice_date or fields.Date.today(),
            'journal_id': journal.id,
            'ref': f'NBET/{cycle.code}/{disco_bill.participant_id.code}-SUBSIDY',
            'narration': f'NBET Subsidy Credit Note — {cycle.name}',
            'company_id': cycle.company_id.id,
            'currency_id': disco_bill.currency_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': f'Government Subsidy Offset — {cycle.name}',
                'quantity': 1.0,
                'price_unit': disco_bill.subsidy_amount,
                'account_id': account.id,
            })],
        }
        return self.env['account.move'].create(move_vals)

    def _create_subsidy_receivable_entry(self, disco_bill, cfg):
        """Create a journal entry for the subsidy receivable (mode 3)."""
        if not cfg.subsidy_partner_id:
            _logger.warning('No subsidy partner configured; skipping subsidy receivable entry.')
            return False
        account = cfg.subsidy_receivable_account_id
        revenue_account = cfg.revenue_energy_account_id
        if not account or not revenue_account:
            _logger.warning('Missing subsidy accounts; skipping subsidy receivable entry.')
            return False

        cycle = disco_bill.billing_cycle_id
        journal = cfg.subsidy_journal_id or self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', cycle.company_id.id)], limit=1
        )

        move_vals = {
            'move_type': 'entry',
            'partner_id': cfg.subsidy_partner_id.id,
            'date': cycle.invoice_date or fields.Date.today(),
            'journal_id': journal.id,
            'ref': f'NBET/{cycle.code}/{disco_bill.participant_id.code}-SUBSIDY-REC',
            'narration': f'NBET Subsidy Receivable — {cycle.name} / {disco_bill.participant_id.name}',
            'company_id': cycle.company_id.id,
            'currency_id': disco_bill.currency_id.id,
            'line_ids': [
                (0, 0, {
                    'name': f'Subsidy Receivable — {disco_bill.participant_id.name}',
                    'account_id': account.id,
                    'debit': disco_bill.subsidy_amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': f'Revenue Offset — {disco_bill.participant_id.name}',
                    'account_id': revenue_account.id,
                    'debit': 0.0,
                    'credit': disco_bill.subsidy_amount,
                }),
            ],
        }
        return self.env['account.move'].create(move_vals)

    def _build_disco_invoice_lines(self, disco_bill, cfg, include_subsidy=False):
        """Build invoice line dicts for a DISCO bill."""
        lines = []
        for bl in disco_bill.line_ids:
            if bl.is_subsidy_line and not include_subsidy:
                continue
            account = self._get_account_for_line_type(bl.line_type, 'disco', cfg)
            if not account:
                continue
            lines.append({
                'name': bl.description or bl.line_type,
                'quantity': 1.0,
                'price_unit': bl.amount,
                'account_id': account.id,
            })
        return lines

    # ──────────────────────────────────────────────────────────────────────────
    # Adjustment Journal Entry
    # ──────────────────────────────────────────────────────────────────────────

    def create_adjustment_entry(self, adjustment, cfg=None):
        """Create a journal entry for an approved billing adjustment."""
        if cfg is None:
            cfg = self.env['nbet.billing.config'].get_config()

        cycle = adjustment.billing_cycle_id
        adj_account = cfg.adjustment_account_id
        if not adj_account:
            _logger.warning('No adjustment account configured.')
            return False

        partner = adjustment.participant_id.partner_id
        journal = cfg.subsidy_journal_id or self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', cycle.company_id.id)], limit=1
        )

        amount = abs(adjustment.amount)
        if adjustment.adjustment_type == 'debit':
            dr_account = adj_account
            cr_account = adj_account  # simplified; use proper contra account in production
        else:
            dr_account = adj_account
            cr_account = adj_account

        move_vals = {
            'move_type': 'entry',
            'partner_id': partner.id if partner else False,
            'date': cycle.invoice_date or fields.Date.today(),
            'journal_id': journal.id,
            'ref': f'NBET-ADJ/{cycle.code}/{adjustment.reference or adjustment.id}',
            'narration': adjustment.description,
            'company_id': cycle.company_id.id,
            'currency_id': adjustment.currency_id.id,
            'line_ids': [
                (0, 0, {
                    'name': adjustment.description,
                    'account_id': dr_account.id,
                    'debit': amount if adjustment.adjustment_type == 'debit' else 0.0,
                    'credit': amount if adjustment.adjustment_type == 'credit' else 0.0,
                }),
                (0, 0, {
                    'name': adjustment.description,
                    'account_id': cr_account.id,
                    'debit': amount if adjustment.adjustment_type == 'credit' else 0.0,
                    'credit': amount if adjustment.adjustment_type == 'debit' else 0.0,
                }),
            ],
        }
        return self.env['account.move'].create(move_vals)

    # ──────────────────────────────────────────────────────────────────────────
    # Account Resolution
    # ──────────────────────────────────────────────────────────────────────────

    def _get_account_for_line_type(self, line_type, participant_role, cfg):
        """Map a bill line_type to an account.account based on config."""
        mapping = {
            ('capacity', 'genco'): cfg.expense_capacity_account_id,
            ('energy', 'genco'): cfg.expense_energy_account_id,
            ('import', 'genco'): cfg.import_charge_account_id,
            ('adjustment', 'genco'): cfg.adjustment_account_id,
            ('capacity', 'disco'): cfg.revenue_capacity_account_id,
            ('energy', 'disco'): cfg.revenue_energy_account_id,
            ('adjustment', 'disco'): cfg.adjustment_account_id,
            ('subsidy', 'disco'): cfg.subsidy_receivable_account_id,
            ('grant', 'disco'): cfg.grant_receivable_account_id,
        }
        return mapping.get((line_type, participant_role))
