# -*- coding: utf-8 -*-
"""
Meristem DISCO Collection Advice — Unit Tests
Run with:
  python odoo-bin -d <db> --test-enable --test-tags /nbet_power_billing -u nbet_power_billing
"""
from odoo.tests import tagged, new_test_user
from odoo.tests.common import TransactionCase
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import ValidationError, UserError


class TestCollectionAmounts(TransactionCase):
    """Rollups and constraints, with confirmation states written directly so
    no accounting is involved."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Participant = cls.env['nbet.market.participant']
        cls.disco_a = Participant.create({
            'name': 'Disco Alpha', 'code': 'DA', 'participant_type': 'disco',
        })
        cls.disco_b = Participant.create({
            'name': 'Disco Beta', 'code': 'DB', 'participant_type': 'disco',
        })
        cls.cycle = cls.env['nbet.billing.cycle'].create({
            'name': 'Test Cycle', 'code': 'CA-01',
            'date_start': '2026-01-01', 'date_end': '2026-01-31',
        })
        cls.cycle.state = 'posted'

    def _make_advice(self, amounts=None):
        advice = self.env['nbet.collection.advice'].create({
            'billing_cycle_id': self.cycle.id,
        })
        for participant, amount in (amounts or {}).items():
            self.env['nbet.collection.advice.line'].create({
                'advice_id': advice.id,
                'participant_id': participant.id,
                'amount_advised': amount,
            })
        return advice

    def _confirm(self, line, status, amount, state='posted'):
        return self.env['nbet.collection.confirmation'].create({
            'line_id': line.id,
            'status': status,
            'amount': amount,
            'state': state,
        })

    def test_sequence_assigned(self):
        advice = self._make_advice()
        self.assertTrue(advice.name.startswith('MCA/'))
        line = self._make_advice({self.disco_a: 100.0}).line_ids
        confirmation = self._confirm(line, 'not_seen', 100.0, state='draft')
        self.assertTrue(confirmation.name.startswith('MCC/'))

    def test_rollups_split_by_status(self):
        advice = self._make_advice({self.disco_a: 500.0, self.disco_b: 200.0})
        line_a = advice.line_ids.filtered(
            lambda l: l.participant_id == self.disco_a)
        self._confirm(line_a, 'in_bank', 300.0)
        self._confirm(line_a, 'with_remita', 150.0)
        # Draft confirmations must not count.
        self._confirm(line_a, 'not_seen', 50.0, state='draft')

        self.assertAlmostEqual(line_a.amount_in_bank, 300.0, places=2)
        self.assertAlmostEqual(line_a.amount_with_remita, 150.0, places=2)
        self.assertAlmostEqual(line_a.amount_not_seen, 0.0, places=2)
        self.assertAlmostEqual(line_a.amount_pending, 50.0, places=2)
        self.assertEqual(line_a.verification_status, 'partial')

        self.assertAlmostEqual(advice.total_advised, 700.0, places=2)
        self.assertAlmostEqual(advice.total_in_bank, 300.0, places=2)
        self.assertAlmostEqual(advice.total_with_remita, 150.0, places=2)
        self.assertAlmostEqual(advice.total_pending, 250.0, places=2)

        self.assertAlmostEqual(self.cycle.total_collection_advised, 700.0, places=2)
        self.assertAlmostEqual(self.cycle.total_collection_in_bank, 300.0, places=2)
        self.assertAlmostEqual(self.cycle.total_collection_with_remita, 150.0, places=2)

    def test_cycle_aggregates_multiple_advices(self):
        self._make_advice({self.disco_a: 500.0})
        self._make_advice({self.disco_b: 200.0})
        self.assertAlmostEqual(self.cycle.total_collection_advised, 700.0, places=2)

        cancelled = self._make_advice({self.disco_a: 999.0})
        cancelled.action_cancel()
        self.assertAlmostEqual(self.cycle.total_collection_advised, 700.0, places=2,
                               msg='Cancelled advices must not count')

    def test_full_verification_marks_line(self):
        advice = self._make_advice({self.disco_a: 500.0})
        line = advice.line_ids
        self._confirm(line, 'in_bank', 400.0)
        self._confirm(line, 'not_seen', 100.0)
        self.assertEqual(line.verification_status, 'full')
        self.assertAlmostEqual(line.amount_pending, 0.0, places=2)

    def test_over_confirmation_blocked(self):
        advice = self._make_advice({self.disco_a: 500.0})
        line = advice.line_ids
        self._confirm(line, 'in_bank', 400.0)
        with self.assertRaises(ValidationError):
            self._confirm(line, 'with_remita', 200.0)

    def test_advised_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._make_advice({self.disco_a: 0.0})

    def test_disco_unique_per_advice(self):
        advice = self._make_advice({self.disco_a: 100.0})
        with self.assertRaises(Exception):
            self.env['nbet.collection.advice.line'].create({
                'advice_id': advice.id,
                'participant_id': self.disco_a.id,
                'amount_advised': 50.0,
            })

    def test_cycle_state_gate(self):
        draft_cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Draft Cycle', 'code': 'CA-02',
            'date_start': '2026-02-01', 'date_end': '2026-02-28',
        })
        with self.assertRaises(ValidationError):
            self.env['nbet.collection.advice'].create({
                'billing_cycle_id': draft_cycle.id,
            })

    def test_confirm_requires_lines(self):
        advice = self._make_advice()
        with self.assertRaises(UserError):
            advice.action_confirm()
        self.env['nbet.collection.advice.line'].create({
            'advice_id': advice.id,
            'participant_id': self.disco_a.id,
            'amount_advised': 100.0,
        })
        advice.action_confirm()
        self.assertEqual(advice.state, 'confirmed')

    def test_cancel_blocked_by_posted_confirmations(self):
        advice = self._make_advice({self.disco_a: 100.0})
        advice.action_confirm()
        confirmation = self._confirm(advice.line_ids, 'with_remita', 100.0,
                                     state='draft')
        advice_2 = self._make_advice({self.disco_b: 100.0})
        advice_2.action_cancel()  # no posted confirmations: fine
        self.assertEqual(advice_2.state, 'cancelled')

        confirmation.state = 'posted'
        with self.assertRaises(UserError):
            advice.action_cancel()

    def test_delete_only_draft_or_cancelled(self):
        advice = self._make_advice({self.disco_a: 100.0})
        advice.action_confirm()
        with self.assertRaises(UserError):
            advice.unlink()
        advice.action_reset_to_draft()
        advice.unlink()


@tagged('post_install', '-at_install')
class TestCollectionConfirmation(AccountTestInvoicingCommon):
    """Bank confirmations against real posted moves: payment creation,
    oldest-first reconciliation, and the guard rails around them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Participant = cls.env['nbet.market.participant']
        cls.disco = Participant.create({
            'name': 'Disco One', 'code': 'D1', 'participant_type': 'disco',
            'partner_id': cls.partner_a.id,
        })
        cls.disco_no_partner = Participant.create({
            'name': 'Disco Orphan', 'code': 'D2', 'participant_type': 'disco',
        })
        cls.cycle = cls.env['nbet.billing.cycle'].create({
            'name': 'Test Cycle', 'code': 'CC-01',
            'date_start': '2026-01-01', 'date_end': '2026-01-31',
        })
        cls.invoice_old = cls._make_invoice(cls.partner_a, 600.0, cls.disco,
                                            '2026-01-15')
        cls.invoice_new = cls._make_invoice(cls.partner_a, 400.0, cls.disco,
                                            '2026-01-31')
        cls.cycle.state = 'posted'
        cls.bank_journal = cls.company_data['default_journal_bank']

        cls.accountant = new_test_user(
            cls.env, login='ca_accountant',
            groups='nbet_power_billing.group_nbet_accounting_officer,'
                   'account.group_account_invoice',
        )
        cls.officer = new_test_user(
            cls.env, login='ca_officer',
            groups='nbet_power_billing.group_nbet_billing_officer',
        )

    @classmethod
    def _make_invoice(cls, partner, amount, participant, invoice_date):
        move = cls.init_invoice(
            'out_invoice', partner=partner, invoice_date=invoice_date,
            amounts=[amount], taxes=cls.env['account.tax'], post=True,
        )
        move.sudo().with_context(skip_is_manually_modified=True).write({
            'nbet_billing_cycle_id': cls.cycle.id,
            'nbet_participant_id': participant.id,
            'nbet_settlement_role': 'disco',
        })
        return move

    def _confirmed_advice(self, participant=None, amount=500.0):
        advice = self.env['nbet.collection.advice'].create({
            'billing_cycle_id': self.cycle.id,
        })
        self.env['nbet.collection.advice.line'].create({
            'advice_id': advice.id,
            'participant_id': (participant or self.disco).id,
            'amount_advised': amount,
        })
        advice.action_confirm()
        return advice

    def _confirmation(self, advice, status, amount, **extra):
        vals = {
            'line_id': advice.line_ids[0].id,
            'status': status,
            'amount': amount,
        }
        if status == 'in_bank':
            vals.update({
                'journal_id': self.bank_journal.id,
                'payment_reference': 'BANKREF/001',
            })
        vals.update(extra)
        return self.env['nbet.collection.confirmation'].create(vals)

    def test_in_bank_creates_and_reconciles_payment_oldest_first(self):
        advice = self._confirmed_advice(amount=500.0)
        confirmation = self._confirmation(advice, 'in_bank', 700.0)
        confirmation.with_user(self.accountant).action_post()

        self.assertEqual(confirmation.state, 'posted')
        payment = confirmation.payment_id
        self.assertTrue(payment)
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(payment.payment_type, 'inbound')
        self.assertAlmostEqual(payment.amount, 700.0, places=2)

        # Oldest first: the 600 invoice is fully settled, the newer 400
        # invoice absorbs the remaining 100.
        self.assertAlmostEqual(self.invoice_old.amount_residual, 0.0, places=2)
        self.assertAlmostEqual(self.invoice_new.amount_residual, 300.0, places=2)

        self.assertAlmostEqual(self.cycle.total_collection_in_bank, 700.0, places=2)
        self.assertAlmostEqual(self.cycle.total_payment_received, 700.0, places=2)

    def test_tracking_statuses_create_no_payment_and_close_advice(self):
        advice = self._confirmed_advice(amount=500.0)
        in_bank = self._confirmation(advice, 'in_bank', 300.0)
        in_bank.with_user(self.accountant).action_post()

        remita = self._confirmation(advice, 'with_remita', 200.0)
        remita.with_user(self.accountant).action_post()
        self.assertFalse(remita.payment_id)
        self.assertEqual(advice.state, 'done',
                         'Advice closes once every naira is accounted for')

        # Correction path: the Remita entry cancels freely, reopening the
        # advice; the bank entry is locked behind its payment.
        remita.action_cancel()
        self.assertEqual(remita.state, 'cancelled')
        self.assertEqual(advice.state, 'confirmed')
        with self.assertRaises(UserError):
            in_bank.action_cancel()

    def test_post_needs_accounting_group(self):
        advice = self._confirmed_advice()
        confirmation = self._confirmation(advice, 'with_remita', 100.0)
        with self.assertRaises(UserError):
            confirmation.with_user(self.officer).action_post()

    def test_post_guards(self):
        advice = self._confirmed_advice(amount=500.0)

        over = self._confirmation(advice, 'with_remita', 600.0)
        with self.assertRaises(UserError):
            over.with_user(self.accountant).action_post()

        no_journal = self._confirmation(advice, 'in_bank', 100.0,
                                        journal_id=False)
        with self.assertRaises(UserError):
            no_journal.with_user(self.accountant).action_post()

        no_reference = self._confirmation(advice, 'in_bank', 100.0,
                                          payment_reference=False)
        with self.assertRaises(UserError):
            no_reference.with_user(self.accountant).action_post()

    def test_post_requires_partner_and_open_invoice(self):
        advice = self._confirmed_advice(participant=self.disco_no_partner,
                                        amount=100.0)
        confirmation = self._confirmation(advice, 'in_bank', 100.0)
        with self.assertRaises(UserError):
            confirmation.with_user(self.accountant).action_post()

        # partner_b has no cycle invoices at all.
        disco_b = self.env['nbet.market.participant'].create({
            'name': 'Disco Two', 'code': 'D3', 'participant_type': 'disco',
            'partner_id': self.partner_b.id,
        })
        advice_b = self._confirmed_advice(participant=disco_b, amount=100.0)
        confirmation_b = self._confirmation(advice_b, 'in_bank', 100.0)
        with self.assertRaises(UserError):
            confirmation_b.with_user(self.accountant).action_post()

    def test_draft_advice_blocks_posting(self):
        advice = self.env['nbet.collection.advice'].create({
            'billing_cycle_id': self.cycle.id,
        })
        line = self.env['nbet.collection.advice.line'].create({
            'advice_id': advice.id,
            'participant_id': self.disco.id,
            'amount_advised': 100.0,
        })
        confirmation = self.env['nbet.collection.confirmation'].create({
            'line_id': line.id, 'status': 'not_seen', 'amount': 100.0,
        })
        with self.assertRaises(UserError):
            confirmation.with_user(self.accountant).action_post()
