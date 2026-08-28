# -*- coding: utf-8 -*-
"""
Billing → Treasury bridge — Unit Tests
Run with:
  python odoo-bin -d <db> --test-enable --test-tags /nbet_billing_treasury -i nbet_billing_treasury
"""
from odoo.tests import tagged, new_test_user
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestBillingTreasury(AccountTestInvoicingCommon):

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
            'name': 'Bridge Cycle', 'code': 'BC-01',
            'date_start': '2026-01-01', 'date_end': '2026-01-31',
        })
        cls.bill_a = cls._make_move('in_invoice', cls.partner_a, 600.0, cls.genco_a)
        cls.bill_b = cls._make_move('in_invoice', cls.partner_b, 400.0, cls.genco_b)
        cls.disco_invoice = cls._make_move(
            'out_invoice', cls.disco_partner, 1000.0, cls.disco)
        cls.cycle.state = 'posted'

        cls.billing_manager = new_test_user(
            cls.env, login='bt_manager',
            groups='nbet_power_billing.group_nbet_settlement_manager',
        )
        cls.ocma_user = new_test_user(
            cls.env, login='bt_ocma',
            groups='nbet_power_billing.group_nbet_ocma_head',
        )
        cls.md_user = new_test_user(
            cls.env, login='bt_md',
            groups='nbet_power_billing.group_nbet_md',
        )
        cls.treasurer = new_test_user(
            cls.env, login='bt_treasurer',
            groups='nbet_treasury.group_treasury_manager',
        )
        cls.cfo_user = new_test_user(
            cls.env, login='bt_cfo', groups='nbet_treasury.group_cfo',
        )
        cls.fm_user = new_test_user(
            cls.env, login='bt_fm', groups='nbet_treasury.group_finance_manager',
        )
        cls.fin_officer = new_test_user(
            cls.env, login='bt_finoff', groups='nbet_treasury.group_treasury_user',
        )
        cls.audit1 = new_test_user(
            cls.env, login='bt_audit1', groups='nbet_treasury.group_auditor',
        )
        cls.audit2 = new_test_user(
            cls.env, login='bt_audit2', groups='nbet_treasury.group_auditor',
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

    def _pay_disco(self, amount):
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=self.disco_invoice.ids,
        ).create({'amount': amount}).action_create_payments()

    def _approved_advice(self, collections=300.0):
        self._pay_disco(collections)
        advice = self.env['nbet.payment.advice'].create({
            'billing_cycle_id': self.cycle.id,
        })
        advice.action_generate_lines()
        advice.action_submit()
        advice.with_user(self.ocma_user).action_ocma_approve()
        advice.with_user(self.md_user).action_md_approve()
        return advice

    # ── Hand-off ───────────────────────────────────────────────────────────────
    def test_send_to_treasury(self):
        advice = self._approved_advice()
        advice.with_user(self.billing_manager).action_send_to_treasury()

        self.assertEqual(advice.state, 'sent_to_treasury')
        schedule = advice.payment_schedule_id
        self.assertTrue(schedule)
        self.assertEqual(schedule.source_type, 'power_billing')
        self.assertEqual(schedule.payment_advice_id, advice)
        self.assertAlmostEqual(schedule.amount, 300.0, places=2)
        self.assertFalse(schedule.tax_line_ids,
                         'No rule-based deductions on a payment advice')
        self.assertAlmostEqual(schedule.net_amount, 300.0, places=2)

        with self.assertRaises(UserError):
            advice.with_user(self.billing_manager).action_send_to_treasury()

    def test_send_requires_md_approval(self):
        self._pay_disco(300.0)
        advice = self.env['nbet.payment.advice'].create({
            'billing_cycle_id': self.cycle.id,
        })
        advice.action_generate_lines()
        with self.assertRaises(UserError):
            advice.with_user(self.billing_manager).action_send_to_treasury()

    def test_cancel_blocked_while_with_treasury(self):
        advice = self._approved_advice()
        advice.with_user(self.billing_manager).action_send_to_treasury()
        with self.assertRaises(UserError):
            advice.with_user(self.billing_manager).action_cancel()

    # ── Vouchers ───────────────────────────────────────────────────────────────
    def _schedule_through_fm(self, advice):
        schedule = advice.payment_schedule_id
        schedule.with_user(self.treasurer).write({
            'scheduled_date': '2026-02-05',
            'payment_method': 'bank_transfer',
            'payment_journal_id': self.company_data['default_journal_bank'].id,
        })
        schedule.with_user(self.treasurer).action_schedule()
        schedule.with_user(self.cfo_user).action_cfo_approve()
        schedule.with_user(self.fm_user).action_fm_approve()
        schedule.with_user(self.treasurer).finance_officer_id = self.fin_officer
        return schedule

    def test_voucher_generation_one_per_genco(self):
        advice = self._approved_advice()
        advice.with_user(self.billing_manager).action_send_to_treasury()
        schedule = self._schedule_through_fm(advice)

        schedule.with_user(self.fin_officer).action_generate_vouchers()
        vouchers = schedule.voucher_ids
        self.assertEqual(len(vouchers), 2)
        self.assertTrue(all(v.voucher_type == 'genco' for v in vouchers))
        voucher_a = vouchers.filtered(lambda v: v.partner_id == self.partner_a)
        self.assertAlmostEqual(voucher_a.amount, 180.0, places=2)
        self.assertEqual(voucher_a.advice_line_id.participant_id, self.genco_a)

    def test_voucher_generation_blocks_stale_amounts(self):
        advice = self._approved_advice()
        advice.with_user(self.billing_manager).action_send_to_treasury()
        schedule = self._schedule_through_fm(advice)
        # The bills get settled by other means after MD approval.
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=self.bill_a.ids,
        ).create({}).action_create_payments()
        with self.assertRaises(UserError):
            schedule.with_user(self.fin_officer).action_generate_vouchers()

    # ── Settlement end-to-end ──────────────────────────────────────────────────
    def test_payment_reconciles_and_settles(self):
        advice = self._approved_advice()
        advice.with_user(self.billing_manager).action_send_to_treasury()
        schedule = self._schedule_through_fm(advice)
        schedule.with_user(self.fin_officer).action_generate_vouchers()
        schedule.with_user(self.fin_officer).action_forward_to_audit()
        schedule.with_user(self.audit1).action_audit_review()
        schedule.with_user(self.audit2).action_audit_approve()

        residual_a_before = self.bill_a.amount_residual
        residual_b_before = self.bill_b.amount_residual
        for voucher in schedule.voucher_ids:
            voucher.with_user(self.treasurer).write({
                'payment_reference': 'TRF-%s' % voucher.id,
                'payment_journal_id': self.company_data['default_journal_bank'].id,
            })
            voucher.with_user(self.treasurer).action_register_payment()
            self.assertEqual(voucher.state, 'paid')
            self.assertTrue(voucher.payment_id)

        self.assertAlmostEqual(
            self.bill_a.amount_residual, residual_a_before - 180.0, places=2)
        self.assertAlmostEqual(
            self.bill_b.amount_residual, residual_b_before - 120.0, places=2)
        self.assertEqual(schedule.state, 'paid')
        self.assertEqual(advice.state, 'paid')

    def test_paid_advice_frees_no_genco_outstanding_but_keeps_pool(self):
        advice = self._approved_advice()
        advice.with_user(self.billing_manager).action_send_to_treasury()
        schedule = self._schedule_through_fm(advice)
        schedule.with_user(self.fin_officer).action_generate_vouchers()
        schedule.with_user(self.fin_officer).action_forward_to_audit()
        schedule.with_user(self.audit1).action_audit_review()
        schedule.with_user(self.audit2).action_audit_approve()
        for voucher in schedule.voucher_ids:
            voucher.with_user(self.treasurer).write({
                'payment_reference': 'TRF-%s' % voucher.id,
                'payment_journal_id': self.company_data['default_journal_bank'].id,
            })
            voucher.with_user(self.treasurer).action_register_payment()

        # More cash arrives; a second advice sees the paid advice still charged
        # against the pool, and the reduced bill residuals (600-180=420,
        # 400-120=280) — not a double deduction.
        self._pay_disco(500.0)
        second = self.env['nbet.payment.advice'].create({
            'billing_cycle_id': self.cycle.id,
        })
        second.action_generate_lines()
        self.assertAlmostEqual(second.pool_collections_received, 800.0, places=2)
        self.assertAlmostEqual(second.pool_previously_advised, 300.0, places=2)
        self.assertAlmostEqual(second.pool_available, 500.0, places=2)
        line_a = second.line_ids.filtered(lambda l: l.participant_id == self.genco_a)
        self.assertAlmostEqual(line_a.outstanding_amount, 420.0, places=2)
