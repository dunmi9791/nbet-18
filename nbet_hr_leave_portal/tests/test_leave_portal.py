# -*- coding: utf-8 -*-
import re

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'nbet_leave_portal')
class TestLeavePortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A portal user with a linked employee.
        cls.portal_user = cls.env['res.users'].create({
            'name': 'Portal Employee',
            'login': 'portal_employee',
            'password': 'portal_employee',
            'email': 'portal.employee@example.com',
            'groups_id': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Portal Employee',
            'user_id': cls.portal_user.id,
            'work_email': 'portal.employee@example.com',
        })
        # A leave type that needs no prior allocation, so a request can be
        # submitted without first creating an allocation.
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Portal Unpaid',
            'requires_allocation': 'no',
            'leave_validation_type': 'hr',
        })
        # A leave belonging to a *different* employee, used to assert isolation.
        other_user = cls.env['res.users'].create({
            'name': 'Other Portal',
            'login': 'other_portal',
            'password': 'other_portal',
            'groups_id': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })
        cls.other_employee = cls.env['hr.employee'].create({
            'name': 'Other Employee',
            'user_id': other_user.id,
        })
        cls.other_leave = cls.env['hr.leave'].create({
            'name': 'Other leave',
            'employee_id': cls.other_employee.id,
            'holiday_status_id': cls.leave_type.id,
            'request_date_from': '2026-07-06',
            'request_date_to': '2026-07-06',
        })

    def _csrf_token(self, html):
        match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        self.assertTrue(match, "CSRF token not found in form page")
        return match.group(1)

    def test_01_pages_load(self):
        self.authenticate('portal_employee', 'portal_employee')
        for url in ('/my/leaves', '/my/leaves/allocations', '/my/leave/new'):
            resp = self.url_open(url)
            self.assertEqual(resp.status_code, 200, "%s should load" % url)

    def test_02_submit_request(self):
        self.authenticate('portal_employee', 'portal_employee')
        form_page = self.url_open('/my/leave/new')
        csrf = self._csrf_token(form_page.text)

        resp = self.url_open('/my/leave/new', data={
            'csrf_token': csrf,
            'holiday_status_id': self.leave_type.id,
            'request_date_from': '2026-07-06',
            'request_date_to': '2026-07-07',
            'name': 'Family time',
        })
        self.assertEqual(resp.status_code, 200)

        leave = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee.id),
            ('name', '=', 'Family time'),
        ])
        self.assertEqual(len(leave), 1, "A leave request should have been created")
        self.assertEqual(leave.holiday_status_id, self.leave_type)
        # It must leave the draft state and reach the approver.
        self.assertNotEqual(leave.state, 'draft')

    def test_03_cannot_see_other_employee_leave(self):
        self.authenticate('portal_employee', 'portal_employee')
        # Detail of someone else's leave must redirect away, not expose data.
        resp = self.url_open('/my/leave/%s' % self.other_leave.id, allow_redirects=False)
        self.assertIn(resp.status_code, (301, 302, 303))
        self.assertIn('/my/leaves', resp.headers.get('Location', ''))

    def test_04_grant_portal_access_action(self):
        action = self.employee.action_grant_leave_portal_access()
        self.assertEqual(action['res_model'], 'portal.wizard')
        self.assertTrue(action['context'].get('active_ids'))
