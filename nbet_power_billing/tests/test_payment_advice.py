# -*- coding: utf-8 -*-
"""
GENCO Payment Advice — Unit Tests
Run with:
  python odoo-bin -d <db> --test-enable --test-tags /nbet_power_billing -u nbet_power_billing
"""
from odoo.tests import tagged, new_test_user
from odoo.tests.common import TransactionCase
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import ValidationError, UserError


class TestAllocationMath(TransactionCase):
    """The largest-remainder pro-rata helper, hit directly."""

    def _allocate(self, target, outstanding_map, rounding=0.01):
        return self.env['nbet.payment.advice']._allocate_largest_remainder(
            target, outstanding_map, rounding)

    def test_simple_pro_rata(self):
        shares = self._allocate(300.0, {1: 600.0, 2: 400.0})
        self.assertAlmostEqual(shares[1], 180.0, places=2)
        self.assertAlmostEqual(shares[2], 120.0, places=2)

    def test_rounding_sums_to_target(self):
        outstanding = {1: 33.33, 2: 33.33, 3: 33.34}
        shares = self._allocate(10.0, outstanding)
        self.assertAlmostEqual(sum(shares.values()), 10.0, places=2)
        for key, share in shares.items():
            self.assertLessEqual(share, outstanding[key])

    def test_awkward_rounding_sums_to_target(self):
        outstanding = {1: 100.0, 2: 100.0, 3: 100.0}
        shares = self._allocate(100.0, outstanding)
        self.assertAlmostEqual(sum(shares.values()), 100.0, places=2)

    def test_pool_covers_everything(self):
        outstanding = {1: 600.0, 2: 400.0}
        shares = self._allocate(5000.0, outstanding)
        self.assertEqual(shares, outstanding)

    def test_empty_outstanding(self):
        self.assertEqual(self._allocate(100.0, {}), {})
        self.assertEqual(self._allocate(100.0, {1: 0.0}), {1: 0.0})


@tagged('post_install', '-at_install')
class TestPaymentAdvice(AccountTestInvoicingCommon):
    """Advice generation, pool snapshot, constraints and approvals against
    real posted moves."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Participant = cls.env['nbet.market.participant']
        cls.genco_a = Participant.create({
            'name': 'Genco Alpha', 'code': 'GA', 'participant_type': 'genco',
            'partner_id': cls.partner_a.id,
        })
        cls.genco_b = Participant.create({
            'name': 'Genco Beta', 'code': 'GB', 'participant_type': 'genco',
            'partner_id': cls.partner_b.id,
        })
        cls.disco_partner = cls.env['res.partner'].create({'name': 'Disco One'})
        cls.disco = Participant.create({
            'name': 'Disco One', 'code': 'D1', 'participant_type': 'disco',
            'partner_id': cls.disco_partner.id,
        })
        cls.cycle = cls.env['nbet.billing.cycle'].create({
            'name': 'Test Cycle', 'code': 'TC-01',
            'date_start': '2026-01-01', 'date_end': '2026-01-31',
        })
        # Skip the calculation/accounting services: stamp the moves directly and
        # force the cycle to the state a real advice would find it in.
        cls.bill_a = cls._make_move('in_invoice', cls.partner_a, 600.0,
                                    cls.genco_a)
        cls.bill_b = cls._make_move('in_invoice', cls.partner_b, 400.0,
                                    cls.genco_b)
        cls.disco_invoice = cls._make_move('out_invoice', cls.disco_partner,
                                           1000.0, cls.disco)
        cls.cycle.state = 'posted'

        cls.officer = new_test_user(
            cls.env, login='pa_officer',
            groups='nbet_power_billing.group_nbet_billing_officer,account.group_account_invoice',
        )
        cls.ocma_user = new_test_user(
            cls.env, login='pa_ocma',
            groups='nbet_power_billing.group_nbet_ocma_head',
        )
        cls.md_user = new_test_user(
            cls.env, login='pa_md',
            groups='nbet_power_billing.group_nbet_md',
        )
        cls.manager = new_test_user(
            cls.env, login='pa_manager',
            groups='nbet_power_billing.group_nbet_settlement_manager,account.group_account_invoice',
        )

    @classmethod
    def _make_move(cls, move_type, partner, amount, participant):
        move = cls.init_invoice(
            move_type, partner=partner, invoice_date='2026-01-31',
            amounts=[amount], taxes=cls.env['account.tax'], post=True,
        )
        move.sudo().with_context(skip_is_manually_modified=True).write({
            'nbet_billing_cycle_id': cls.cycle.id,
            'nbet_participant_id': participant.id,
        })
        return move

    def _pay(self, move, amount):
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids,
        ).create({'amount': amount}).action_create_payments()

    def _make_advice(self):
        return self.env['nbet.payment.advice'].create({
            'billing_cycle_id': self.cycle.id,
        })

    # ── Generation and pool snapshot ───────────────────────────────────────────
    def test_generation_pro_rata(self):
        self._pay(self.disco_invoice, 300.0)
        advice = self._make_advice()
        advice.action_generate_lines()

        self.assertAlmostEqual(advice.pool_collections_received, 300.0, places=2)
        self.assertAlmostEqual(advice.pool_available, 300.0, places=2)
        self.assertEqual(len(advice.line_ids), 2)
        line_a = advice.line_ids.filtered(lambda l: l.participant_id == self.genco_a)
        line_b = advice.line_ids.filtered(lambda l: l.participant_id == self.genco_b)
        self.assertAlmostEqual(line_a.outstanding_amount, 600.0, places=2)
        self.assertAlmostEqual(line_a.pro_rata_share, 180.0, places=2)
        self.assertAlmostEqual(line_a.advice_amount, 180.0, places=2)
        self.assertAlmostEqual(line_b.advice_amount, 120.0, places=2)
        self.assertAlmostEqual(advice.total_advice_amount, 300.0, places=2)
        self.assertIn(self.bill_a, line_a.vendor_bill_ids)

    def test_snapshot_frozen_until_refresh(self):
        self._pay(self.disco_invoice, 300.0)
        advice = self._make_advice()
        advice.action_generate_lines()
        self.assertAlmostEqual(advice.pool_collections_received, 300.0, places=2)

        self._pay(self.disco_invoice, 200.0)
        self.assertAlmostEqual(advice.pool_collections_received, 300.0, places=2,
                               msg='The snapshot must not move with new cash')
        advice.action_generate_lines()
        self.assertAlmostEqual(advice.pool_collections_received, 500.0, places=2)

    def test_pool_fully_covers_outstanding(self):
        self._pay(self.disco_invoice, 1000.0)
        # Pool (1000) covers the whole outstanding (600 + 400): full settlement.
        advice = self._make_advice()
        advice.action_generate_lines()
        self.assertAlmostEqual(advice.total_advice_amount, 1000.0, places=2)
        line_a = advice.line_ids.filtered(lambda l: l.participant_id == self.genco_a)
        self.assertAlmostEqual(line_a.advice_amount, 600.0, places=2)

    # ── Constraints ────────────────────────────────────────────────────────────
    def test_cycle_state_gate(self):
        draft_cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Draft Cycle', 'code': 'TC-02',
            'date_start': '2026-02-01', 'date_end': '2026-02-28',
        })
        with self.assertRaises(ValidationError):
            self.env['nbet.payment.advice'].create({
                'billing_cycle_id': draft_cycle.id,
            })

    def test_line_amount_capped_by_outstanding(self):
        self._pay(self.disco_invoice, 300.0)
        advice = self._make_advice()
        advice.action_generate_lines()
        line_a = advice.line_ids.filtered(lambda l: l.participant_id == self.genco_a)
        with self.assertRaises(ValidationError):
            line_a.advice_amount = 700.0  # outstanding is 600

    def test_total_capped_by_pool(self):
        self._pay(self.disco_invoice, 300.0)
        advice = self._make_advice()
        advice.action_generate_lines()
        line_a = advice.line_ids.filtered(lambda l: l.participant_id == self.genco_a)
        with self.assertRaises(ValidationError):
            line_a.advice_amount = 500.0  # under outstanding but over the 300 pool

    def test_sibling_advice_reserves_pool(self):
        self._pay(self.disco_invoice, 300.0)
        first = self._make_advice()
        first.action_generate_lines()

        # A draft sibling does not reserve anything.
        second = self._make_advice()
        second.action_generate_lines()
        self.assertAlmostEqual(second.pool_previously_advised, 0.0, places=2)

        first.action_submit()
        second.action_generate_lines()
        self.assertAlmostEqual(second.pool_previously_advised, 300.0, places=2)
        self.assertAlmostEqual(second.pool_available, 0.0, places=2)
        self.assertAlmostEqual(second.total_advice_amount, 0.0, places=2,
                               msg='Nothing left to allocate: the pool is fully reserved')
        line_a = second.line_ids.filtered(lambda l: l.participant_id == self.genco_a)
        self.assertAlmostEqual(line_a.outstanding_amount, 420.0, places=2,
                               msg='Outstanding is net of the first advice\'s reservation')

    def test_submit_resnapshots_and_blocks_overdraw(self):
        self._pay(self.disco_invoice, 300.0)
        first = self._make_advice()
        first.action_generate_lines()
        second = self._make_advice()
        second.action_generate_lines()
        # The first advice claims the pool between the second's generation and
        # its submission.
        first.action_submit()
        with self.assertRaises(UserError):
            second.action_submit()

    # ── Approval workflow ──────────────────────────────────────────────────────
    def _submitted_advice(self):
        self._pay(self.disco_invoice, 300.0)
        advice = self._make_advice()
        advice.action_generate_lines()
        advice.action_submit()
        return advice

    def test_sequence_assigned(self):
        advice = self._make_advice()
        self.assertTrue(advice.name.startswith('PA/'))

    def test_full_approval_chain(self):
        advice = self._submitted_advice()
        self.assertEqual(advice.state, 'submitted')

        advice.with_user(self.ocma_user).action_ocma_approve()
        self.assertEqual(advice.state, 'ocma_approved')
        self.assertEqual(advice.ocma_approver_id, self.ocma_user)

        advice.with_user(self.md_user).action_md_approve()
        self.assertEqual(advice.state, 'md_approved')
        self.assertEqual(advice.md_approver_id, self.md_user)

    def test_ocma_approve_needs_group(self):
        advice = self._submitted_advice()
        with self.assertRaises(UserError):
            advice.with_user(self.officer).action_ocma_approve()

    def test_md_approve_needs_group_and_state(self):
        advice = self._submitted_advice()
        with self.assertRaises(UserError):
            advice.with_user(self.md_user).action_md_approve()  # not OCMA-approved yet
        advice.with_user(self.ocma_user).action_ocma_approve()
        with self.assertRaises(UserError):
            advice.with_user(self.officer).action_md_approve()

    def test_md_segregation_of_duties(self):
        advice = self._submitted_advice()
        both = new_test_user(
            self.env, login='pa_both',
            groups='nbet_power_billing.group_nbet_ocma_head,nbet_power_billing.group_nbet_md',
        )
        advice.with_user(both).action_ocma_approve()
        with self.assertRaises(UserError):
            advice.with_user(both).action_md_approve()

    def test_reject_requires_reason(self):
        advice = self._submitted_advice()
        with self.assertRaises(UserError):
            advice.with_user(self.ocma_user).action_reject()
        advice.rejection_reason = 'Committee deferred the payment.'
        advice.with_user(self.ocma_user).action_reject()
        self.assertEqual(advice.state, 'rejected')

        advice.action_reset_to_draft()
        self.assertEqual(advice.state, 'draft')
        self.assertFalse(advice.submitted_by_id)

    def test_cancel_blocked_in_treasury(self):
        advice = self._submitted_advice()
        advice.state = 'sent_to_treasury'
        with self.assertRaises(UserError):
            advice.with_user(self.manager).action_cancel()

    def test_delete_only_draft_or_cancelled(self):
        advice = self._submitted_advice()
        with self.assertRaises(UserError):
            advice.unlink()
        advice.with_user(self.manager).action_cancel()
        advice.unlink()
