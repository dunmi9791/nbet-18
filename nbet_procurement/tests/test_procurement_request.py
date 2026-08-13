# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError, UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProcurementRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.department = cls.env['hr.department'].create({'name': 'Test Engineering'})
        cls.plan = cls.env['nbet.procurement.plan'].create({
            'fiscal_year': '2026',
            'state': 'implementing',
        })
        cls.plan_line = cls.env['nbet.procurement.plan.line'].create({
            'plan_id': cls.plan.id,
            'description': 'Transformer spares',
            'category': 'goods',
            'quantity': 1.0,
            'estimated_amount': 10_000_000.0,
            'department_id': cls.department.id,
        })
        cls.vendor = cls.env['res.partner'].create({'name': 'Test Vendor Ltd'})

    def _make_request(self, amount, **overrides):
        vals = {
            'title': 'Spares purchase',
            'department_id': self.department.id,
            'plan_id': self.plan.id,
            'plan_line_id': self.plan_line.id,
            'category': 'goods',
            'justification': 'Needed to keep the plant running.',
            'line_ids': [(0, 0, {
                'description': 'Spare part',
                'quantity': 1.0,
                'estimated_unit_cost': amount,
            })],
        }
        vals.update(overrides)
        return self.env['nbet.procurement.request'].create(vals)

    def _approve_fully(self, request):
        request.action_submit()
        request.action_dept_approve()
        request.action_procurement_approve()
        if request.state == 'authority_approval':
            request.action_authority_approve()
        return request

    # ── Numbering / basics ─────────────────────────────────────────────────────
    def test_sequence_and_amount(self):
        req = self._make_request(4_000_000.0)
        self.assertTrue(req.name.startswith('PRQ/'), req.name)
        self.assertEqual(req.estimated_amount, 4_000_000.0)
        self.assertEqual(req.state, 'draft')

    # ── Budget position ────────────────────────────────────────────────────────
    def test_draft_does_not_commit_budget(self):
        self._make_request(4_000_000.0)
        self.plan_line.invalidate_recordset()
        self.assertEqual(self.plan_line.committed_amount, 0.0)
        self.assertEqual(self.plan_line.available_amount, 10_000_000.0)

    def test_submission_commits_budget(self):
        req = self._make_request(4_000_000.0)
        req.action_submit()
        self.assertEqual(req.state, 'dept_approval')
        self.assertEqual(self.plan_line.committed_amount, 4_000_000.0)
        self.assertEqual(self.plan_line.available_amount, 6_000_000.0)
        self.assertAlmostEqual(self.plan_line.utilisation_percent, 40.0, places=2)
        self.assertEqual(self.plan.total_committed, 4_000_000.0)
        self.assertEqual(self.plan.total_available, 6_000_000.0)

    def test_soft_reserve_across_pending_requests(self):
        """A request reserves from submission, not from approval, so a second
        department cannot spend the same envelope while the first is pending."""
        first = self._make_request(4_000_000.0)
        first.action_submit()
        second = self._make_request(4_000_000.0)
        second.action_submit()
        self.assertEqual(first.state, 'dept_approval')
        self.assertEqual(self.plan_line.committed_amount, 8_000_000.0)
        self.assertEqual(first.plan_line_committed_other, 4_000_000.0)
        self.assertEqual(first.plan_line_available, 6_000_000.0)

    def test_over_budget_submission_blocked(self):
        self._make_request(4_000_000.0).action_submit()
        self._make_request(4_000_000.0).action_submit()
        third = self._make_request(3_000_000.0)
        with self.assertRaises(ValidationError):
            third.action_submit()

    def test_editing_submitted_request_upward_blocked(self):
        req = self._make_request(4_000_000.0)
        req.action_submit()
        with self.assertRaises(ValidationError):
            req.line_ids[0].estimated_unit_cost = 11_000_000.0
            req.flush_recordset()

    def test_plan_line_cannot_shrink_below_commitments(self):
        self._make_request(8_000_000.0).action_submit()
        with self.assertRaises(ValidationError):
            self.plan_line.estimated_amount = 5_000_000.0

    def test_rejected_request_releases_budget(self):
        req = self._make_request(8_000_000.0)
        req.action_submit()
        req.rejection_reason = 'Not a priority this quarter.'
        req.action_reject()
        self.assertEqual(self.plan_line.committed_amount, 0.0)
        self.assertEqual(self.plan_line.available_amount, 10_000_000.0)

    # ── Unplanned / emergency ──────────────────────────────────────────────────
    def test_unplanned_requires_justification(self):
        with self.assertRaises(ValidationError):
            self._make_request(
                1_000.0, is_unplanned=True, plan_id=False, plan_line_id=False,
            )

    def test_unplanned_skips_envelope_and_forces_authority(self):
        req = self._make_request(
            50_000_000.0,
            is_unplanned=True,
            plan_id=False,
            plan_line_id=False,
            unplanned_justification='Emergency turbine failure.',
        )
        self._approve_fully(req)
        self.assertEqual(req.state, 'approved')
        self.assertTrue(req.authority_approver_id)
        self.assertEqual(self.plan_line.committed_amount, 0.0)

    def test_plan_line_required_when_planned(self):
        with self.assertRaises(ValidationError):
            self._make_request(1_000.0, plan_id=False, plan_line_id=False)

    # ── Routing ────────────────────────────────────────────────────────────────
    def test_authority_is_suggested_from_threshold(self):
        req = self._make_request(4_000_000.0)
        threshold = self.env['nbet.approval.threshold'].search([
            ('category', '=', 'goods'),
            ('min_amount', '<=', 4_000_000.0),
            '|', ('max_amount', '>=', 4_000_000.0), ('max_amount', '=', 0),
        ], limit=1, order='min_amount desc')
        if threshold:
            self.assertEqual(req.approval_authority, threshold.authority)

    def test_approval_chain_stamps_approvers(self):
        req = self._approve_fully(self._make_request(4_000_000.0))
        self.assertEqual(req.state, 'approved')
        self.assertTrue(req.dept_approver_id)
        self.assertTrue(req.proc_approver_id)
        self.assertTrue(req.authority_approval_date)

    def test_authority_stage_skipped_below_configured_floor(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'nbet_procurement.request_authority_min_amount', '5000000',
        )
        req = self._make_request(1_000_000.0)
        req.action_submit()
        req.action_dept_approve()
        req.action_procurement_approve()
        self.assertEqual(req.state, 'approved')

    # ── Handoff to bid evaluation ──────────────────────────────────────────────
    def test_bid_evaluation_handoff(self):
        req = self._approve_fully(self._make_request(4_000_000.0))
        req.action_create_bid_evaluation()
        evaluation = req.bid_evaluation_id
        self.assertTrue(evaluation)
        self.assertEqual(evaluation.request_id, req)
        self.assertEqual(evaluation.plan_line_id, self.plan_line)
        self.assertEqual(evaluation.description, req.title)
        self.assertEqual(evaluation.category, req.category)
        self.assertEqual(evaluation.department_id, self.department)
        self.assertEqual(req.state, 'in_bidding')
        self.assertEqual(self.plan_line.status, 'in_progress')
        # Still holding budget while in bidding.
        self.assertEqual(self.plan_line.committed_amount, 4_000_000.0)

    def test_bid_evaluation_only_from_approved(self):
        req = self._make_request(4_000_000.0)
        with self.assertRaises(UserError):
            req.action_create_bid_evaluation()

    def test_awarded_amount_rolls_up_to_plan_line(self):
        req = self._approve_fully(self._make_request(4_000_000.0))
        req.action_create_bid_evaluation()
        evaluation = req.bid_evaluation_id
        evaluation.write({
            'recommended_vendor_id': self.vendor.id,
            'recommended_amount': 3_800_000.0,
            'state': 'approved',
        })
        evaluation.action_create_contract_award()
        self.assertEqual(req.state, 'done')
        self.assertEqual(self.plan_line.awarded_amount, 3_800_000.0)
        self.assertEqual(self.plan.total_awarded, 3_800_000.0)

    def test_rejected_evaluation_returns_request_for_retender(self):
        req = self._approve_fully(self._make_request(4_000_000.0))
        req.action_create_bid_evaluation()
        req.bid_evaluation_id.action_reject()
        self.assertEqual(req.state, 'approved')
        self.assertFalse(req.bid_evaluation_id)

    # ── Guards ─────────────────────────────────────────────────────────────────
    def test_submit_requires_items(self):
        req = self._make_request(4_000_000.0, line_ids=[])
        with self.assertRaises(UserError):
            req.action_submit()

    def test_reject_requires_reason(self):
        req = self._make_request(4_000_000.0)
        req.action_submit()
        with self.assertRaises(UserError):
            req.action_reject()

    def test_submitted_request_cannot_be_deleted(self):
        req = self._make_request(4_000_000.0)
        req.action_submit()
        with self.assertRaises(UserError):
            req.unlink()

    # ── Record rules ───────────────────────────────────────────────────────────
    def _make_submitter(self, department):
        user = self.env['res.users'].create({
            'name': 'Submitter %s' % department.name,
            'login': 'submitter_%s' % department.id,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('nbet_procurement.group_procurement_submitter').id,
            ])],
        })
        employee = self.env['hr.employee'].create({
            'name': user.name,
            'user_id': user.id,
            'department_id': department.id,
        })
        department.manager_id = employee
        return user

    def test_submitter_sees_only_own_department_requests(self):
        other_department = self.env['hr.department'].create({'name': 'Test Finance'})
        mine = self._make_submitter(self.department)
        theirs = self._make_submitter(other_department)
        req = self._make_request(4_000_000.0)

        visible_to_mine = self.env['nbet.procurement.request'].with_user(mine).search(
            [('id', '=', req.id)]
        )
        visible_to_theirs = self.env['nbet.procurement.request'].with_user(theirs).search(
            [('id', '=', req.id)]
        )
        self.assertEqual(visible_to_mine, req)
        self.assertFalse(visible_to_theirs)

    def test_submitter_can_read_plan_budget(self):
        """Submitters need the plan item's budget position to compose a request."""
        user = self._make_submitter(self.department)
        line = self.plan_line.with_user(user)
        self.assertEqual(line.estimated_amount, 10_000_000.0)
        self.assertEqual(line.available_amount, 10_000_000.0)

    def test_submitter_blocked_by_existing_commitment(self):
        """A submitter is blocked by what colleagues have already reserved."""
        self._make_request(8_000_000.0).action_submit()
        user = self._make_submitter(self.department)
        mine = self._make_request(4_000_000.0).with_user(user)
        with self.assertRaises(ValidationError):
            mine.action_submit()

    # ── Department ownership of plan items ─────────────────────────────────────
    def test_plan_line_inherits_department_from_assessment(self):
        assessment = self.env['nbet.needs.assessment'].create({
            'fiscal_year': '2026',
            'department_id': self.department.id,
            'state': 'approved',
            'line_ids': [(0, 0, {
                'description': 'Cable drums',
                'category': 'goods',
                'quantity': 2.0,
                'estimated_unit_cost': 500_000.0,
            })],
        })
        plan = self.env['nbet.procurement.plan'].create({
            'fiscal_year': '2026',
            'assessment_ids': [(6, 0, assessment.ids)],
        })
        plan.action_populate_from_assessments()
        self.assertTrue(plan.line_ids)
        self.assertEqual(plan.line_ids.department_id, self.department)

    def test_request_cannot_draw_from_another_department_item(self):
        other_department = self.env['hr.department'].create({'name': 'Test Finance'})
        with self.assertRaises(ValidationError):
            self._make_request(1_000_000.0, department_id=other_department.id)

    def test_submitter_sees_only_own_department_plan_items(self):
        other_department = self.env['hr.department'].create({'name': 'Test Finance'})
        other_line = self.env['nbet.procurement.plan.line'].create({
            'plan_id': self.plan.id,
            'description': 'Finance software',
            'category': 'goods',
            'estimated_amount': 1_000_000.0,
            'department_id': other_department.id,
        })
        user = self._make_submitter(self.department)
        visible = self.env['nbet.procurement.plan.line'].with_user(user).search([
            ('id', 'in', (self.plan_line + other_line).ids),
        ])
        self.assertEqual(visible, self.plan_line)

    def test_submitter_sees_only_plans_carrying_their_items(self):
        other_department = self.env['hr.department'].create({'name': 'Test Finance'})
        other_plan = self.env['nbet.procurement.plan'].create({
            'fiscal_year': '2026',
            'state': 'implementing',
            'line_ids': [(0, 0, {
                'description': 'Finance software',
                'category': 'goods',
                'estimated_amount': 1_000_000.0,
                'department_id': other_department.id,
            })],
        })
        user = self._make_submitter(self.department)
        visible = self.env['nbet.procurement.plan'].with_user(user).search([
            ('id', 'in', (self.plan + other_plan).ids),
        ])
        self.assertEqual(visible, self.plan)

    def test_officer_who_is_also_submitter_still_sees_everything(self):
        """Record rules OR across groups, but only among groups carrying a rule.
        Without a see-everything rule on the officer group, the department-scoped
        submitter rule would silently narrow a Head of Procurement who also
        submits for their own department."""
        other_department = self.env['hr.department'].create({'name': 'Test Finance'})
        other_plan = self.env['nbet.procurement.plan'].create({
            'fiscal_year': '2026',
            'state': 'implementing',
            'line_ids': [(0, 0, {
                'description': 'Finance software',
                'category': 'goods',
                'estimated_amount': 1_000_000.0,
                'department_id': other_department.id,
            })],
        })
        other_request = self._make_request(
            500_000.0,
            department_id=other_department.id,
            plan_id=other_plan.id,
            plan_line_id=other_plan.line_ids.id,
        )
        head = self._make_submitter(self.department)
        head.groups_id = [(4, self.env.ref('nbet_procurement.group_procurement_head').id)]

        self.assertIn(other_plan, self.env['nbet.procurement.plan'].with_user(head).search([]))
        self.assertIn(
            other_plan.line_ids,
            self.env['nbet.procurement.plan.line'].with_user(head).search([]),
        )
        self.assertIn(
            other_request,
            self.env['nbet.procurement.request'].with_user(head).search([]),
        )

    def test_pure_submitter_is_still_scoped(self):
        """The permissive officer rule must not leak to plain submitters."""
        other_department = self.env['hr.department'].create({'name': 'Test Finance'})
        other_line = self.env['nbet.procurement.plan.line'].create({
            'plan_id': self.plan.id,
            'description': 'Finance software',
            'category': 'goods',
            'estimated_amount': 1_000_000.0,
            'department_id': other_department.id,
        })
        user = self._make_submitter(self.department)
        self.assertNotIn(
            other_line,
            self.env['nbet.procurement.plan.line'].with_user(user).search([]),
        )

    def test_bid_evaluation_department_falls_back_to_plan_item(self):
        """An evaluation Procurement raises directly off a plan item still
        carries the owning department."""
        evaluation = self.env['nbet.bid.evaluation'].create({
            'description': 'Direct tender',
            'category': 'goods',
            'plan_line_id': self.plan_line.id,
        })
        self.assertEqual(evaluation.department_id, self.department)
