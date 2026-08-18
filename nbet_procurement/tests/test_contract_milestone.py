# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError, UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestContractMilestone(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Milestone Works Ltd'})
        cls.department = cls.env['hr.department'].create({'name': 'Test Works'})

    def _make_contract(self, amount=100_000_000.0, mode='milestone'):
        return self.env['nbet.contract.award'].create({
            'vendor_id': self.vendor.id,
            'description': 'Substation rehabilitation',
            'category': 'works',
            'award_amount': amount,
            'execution_mode': mode,
        })

    def _make_milestone(self, contract, **overrides):
        vals = {
            'contract_id': contract.id,
            'title': 'Phase',
            'amount_basis': 'percent',
            'percentage': 50.0,
        }
        vals.update(overrides)
        return self.env['nbet.contract.milestone'].create(vals)

    def _certify(self, milestone):
        milestone.action_start()
        milestone.action_mark_delivered()
        milestone.write({'ia_signoff': True, 'user_dept_signoff': True})
        milestone.action_verify()
        return milestone

    def _three_milestones(self, contract):
        """30% / 40% / fixed 30m on a contract already under execution."""
        milestones = (
            self._make_milestone(contract, title='M1', percentage=30.0, sequence=1),
            self._make_milestone(contract, title='M2', percentage=40.0, sequence=2),
            self._make_milestone(
                contract, title='M3', sequence=3,
                amount_basis='fixed', amount=30_000_000.0,
            ),
        )
        contract.write({'state': 'in_execution'})
        return milestones

    # ── Value derivation ───────────────────────────────────────────────────────
    def test_percent_basis_derives_amount(self):
        contract = self._make_contract()
        milestone = self._make_milestone(contract, percentage=30.0)
        self.assertTrue(milestone.name.startswith('MS/'), milestone.name)
        self.assertAlmostEqual(milestone.amount, 30_000_000.0, places=2)

    def test_fixed_basis_derives_percentage(self):
        contract = self._make_contract()
        milestone = self._make_milestone(
            contract, amount_basis='fixed', amount=25_000_000.0,
        )
        self.assertAlmostEqual(milestone.percentage, 25.0, places=2)

    def test_switching_basis_recomputes(self):
        contract = self._make_contract()
        milestone = self._make_milestone(contract, percentage=30.0)
        milestone.write({'amount_basis': 'fixed', 'amount': 45_000_000.0})
        self.assertAlmostEqual(milestone.percentage, 45.0, places=2)
        milestone.write({'amount_basis': 'percent', 'percentage': 10.0})
        self.assertAlmostEqual(milestone.amount, 10_000_000.0, places=2)

    def test_milestones_cannot_exceed_contract_value(self):
        contract = self._make_contract()
        self._three_milestones(contract)
        with self.assertRaises(ValidationError):
            self._make_milestone(contract, title='M4', percentage=10.0, sequence=4)

    def test_contract_rollups(self):
        contract = self._make_contract()
        m1, _m2, _m3 = self._three_milestones(contract)
        self.assertEqual(len(contract.milestone_ids), 3)
        self.assertEqual(contract.milestone_count, 3)
        self.assertAlmostEqual(contract.milestone_total_amount, 100_000_000.0, places=2)
        self.assertAlmostEqual(contract.milestone_unallocated_amount, 0.0, places=2)
        self._certify(m1)
        self.assertAlmostEqual(contract.milestone_progress_percent, 30.0, places=2)

    # ── Milestone certification ────────────────────────────────────────────────
    def test_start_blocked_before_agreement_signed(self):
        contract = self._make_contract()
        milestone = self._make_milestone(contract, percentage=30.0)
        with self.assertRaises(UserError):
            milestone.action_start()

    def test_verify_requires_both_signoffs(self):
        contract = self._make_contract()
        milestone = self._make_milestone(contract, percentage=30.0)
        contract.write({'state': 'in_execution'})
        milestone.action_start()
        milestone.action_mark_delivered()
        with self.assertRaises(UserError):
            milestone.action_verify()
        milestone.ia_signoff = True
        with self.assertRaises(UserError):
            milestone.action_verify()
        milestone.user_dept_signoff = True
        milestone.action_verify()
        self.assertEqual(milestone.state, 'verified')
        self.assertEqual(milestone.verified_by, self.env.user)

    def test_contract_verify_blocked_while_milestones_outstanding(self):
        contract = self._make_contract()
        m1, m2, m3 = self._three_milestones(contract)
        contract.write({'ia_signoff': True, 'user_dept_signoff': True})
        self._certify(m1)
        with self.assertRaises(UserError):
            contract.action_verify()
        self._certify(m2)
        self._certify(m3)
        contract.action_verify()
        self.assertEqual(contract.state, 'verified')

    def test_contract_mark_delivered_blocked_while_milestones_outstanding(self):
        contract = self._make_contract()
        m1, m2, m3 = self._three_milestones(contract)
        with self.assertRaises(UserError):
            contract.action_mark_delivered()
        for milestone in (m1, m2, m3):
            milestone.action_start()
            milestone.action_mark_delivered()
        contract.action_mark_delivered()
        self.assertEqual(contract.state, 'delivered')

    # ── Payment ────────────────────────────────────────────────────────────────
    def _make_payment(self, contract, milestone, amount):
        return self.env['nbet.payment.request'].create({
            'contract_award_id': contract.id,
            'milestone_id': milestone.id,
            'requested_amount': amount,
            'department_id': self.department.id,
        })

    def test_cumulative_claim_capped_at_milestone_value(self):
        contract = self._make_contract()
        m1, _m2, _m3 = self._three_milestones(contract)
        self._certify(m1)
        first = self._make_payment(contract, m1, 20_000_000.0)
        first.action_submit_to_md()
        second = self._make_payment(contract, m1, 15_000_000.0)
        with self.assertRaises(UserError):
            second.action_submit_to_md()
        second.requested_amount = 10_000_000.0
        second.action_submit_to_md()
        self.assertEqual(second.state, 'submitted_to_md')

    def test_milestone_required_on_milestone_contract(self):
        contract = self._make_contract()
        m1, _m2, _m3 = self._three_milestones(contract)
        self._certify(m1)
        request = self.env['nbet.payment.request'].create({
            'contract_award_id': contract.id,
            'requested_amount': 1_000_000.0,
            'department_id': self.department.id,
        })
        with self.assertRaises(UserError):
            request.action_submit_to_md()

    def _approve(self, request):
        request.action_submit_to_md()
        request.action_md_review()
        request.action_send_to_user_dept()
        request.action_user_dept_approve()
        request.action_md_final_approve()
        return request

    def _pay(self, contract, milestone):
        """Drive a claim to paid without touching nbet_treasury's override.

        ``action_send_to_treasury`` is overridden downstream to raise a payment
        schedule and a vendor bill; these tests exercise the procurement layer's
        own bookkeeping, so they call its hook directly.
        """
        request = self._make_payment(contract, milestone, milestone.amount)
        self._approve(request)
        request.write({'state': 'sent_to_treasury'})
        request._flag_milestone_payment_requested()
        request.action_mark_paid()
        return request

    def test_contract_completes_only_after_last_milestone_paid(self):
        contract = self._make_contract()
        m1, m2, m3 = self._three_milestones(contract)

        self._certify(m1)
        self._pay(contract, m1)
        self.assertEqual(m1.state, 'paid')
        self.assertEqual(contract.state, 'in_execution')

        self._certify(m2)
        self._pay(contract, m2)
        self.assertEqual(contract.state, 'in_execution')

        self._certify(m3)
        self._pay(contract, m3)
        self.assertEqual(contract.state, 'completed')
        self.assertAlmostEqual(contract.milestone_paid_amount, 100_000_000.0, places=2)

    def test_single_delivery_contract_unchanged(self):
        contract = self._make_contract(mode='single')
        contract.write({'state': 'verified'})
        request = self.env['nbet.payment.request'].create({
            'contract_award_id': contract.id,
            'requested_amount': 100_000_000.0,
            'department_id': self.department.id,
        })
        self._approve(request)
        request.write({'state': 'sent_to_treasury'})
        request._flag_milestone_payment_requested()
        self.assertEqual(contract.state, 'payment_processing')
        request.action_mark_paid()
        self.assertEqual(contract.state, 'completed')

    def test_contract_level_payment_request_blocked_in_milestone_mode(self):
        contract = self._make_contract()
        self._three_milestones(contract)
        with self.assertRaises(UserError):
            contract.action_create_payment_request()

    # ── Purchase order ─────────────────────────────────────────────────────────
    def test_purchase_order_gets_one_line_per_milestone(self):
        contract = self._make_contract()
        m1, m2, m3 = self._three_milestones(contract)
        contract.action_create_purchase_order()
        po = contract.purchase_order_id
        self.assertEqual(len(po.order_line), 3)
        self.assertEqual(m1.purchase_line_id, po.order_line[0])
        self.assertEqual(m2.purchase_line_id, po.order_line[1])
        self.assertEqual(m3.purchase_line_id, po.order_line[2])
        self.assertAlmostEqual(m1.purchase_line_id.price_unit, 30_000_000.0, places=2)
        self.assertAlmostEqual(m3.purchase_line_id.price_unit, 30_000_000.0, places=2)

    def test_purchase_order_refused_without_milestones(self):
        contract = self._make_contract()
        with self.assertRaises(UserError):
            contract.action_create_purchase_order()
