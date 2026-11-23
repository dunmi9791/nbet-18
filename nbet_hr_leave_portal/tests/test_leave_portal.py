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

    # ------------------------------------------------------------------
    # Live preview, half days, supporting documents, approver
    # ------------------------------------------------------------------
    def test_05_preview_counts_working_days(self):
        self.authenticate('portal_employee', 'portal_employee')
        # 2026-07-06 is a Monday: Mon-Tue = 2 working days.
        result = self.make_jsonrpc_request('/my/leave/preview', {
            'holiday_status_id': self.leave_type.id,
            'date_from': '2026-07-06',
            'date_to': '2026-07-07',
        })
        self.assertEqual(result.get('days'), 2)
        self.assertFalse(result.get('requires_allocation'))

        # Saturday-Sunday uses no working days.
        result = self.make_jsonrpc_request('/my/leave/preview', {
            'holiday_status_id': self.leave_type.id,
            'date_from': '2026-07-11',
            'date_to': '2026-07-12',
        })
        self.assertEqual(result.get('days'), 0)

    def test_06_preview_rejects_unavailable_type(self):
        self.authenticate('portal_employee', 'portal_employee')
        other_company = self.env['res.company'].create({'name': 'Other Co'})
        foreign_type = self.env['hr.leave.type'].create({
            'name': 'Foreign Type',
            'requires_allocation': 'no',
            'company_id': other_company.id,
        })
        result = self.make_jsonrpc_request('/my/leave/preview', {
            'holiday_status_id': foreign_type.id,
            'date_from': '2026-07-06',
            'date_to': '2026-07-07',
        })
        self.assertIn('error', result)
        self.assertNotIn('days', result)

    def test_07_preview_reports_balance(self):
        alloc_type = self.env['hr.leave.type'].create({
            'name': 'Portal Annual',
            'requires_allocation': 'yes',
            'leave_validation_type': 'hr',
        })
        allocation = self.env['hr.leave.allocation'].create({
            'name': 'Annual 2026',
            'employee_id': self.employee.id,
            'holiday_status_id': alloc_type.id,
            'number_of_days': 3,
            'date_from': '2026-01-01',
        })
        allocation.action_approve()
        self.authenticate('portal_employee', 'portal_employee')
        # Mon-Fri = 5 days against a balance of 3.
        result = self.make_jsonrpc_request('/my/leave/preview', {
            'holiday_status_id': alloc_type.id,
            'date_from': '2026-07-13',
            'date_to': '2026-07-17',
        })
        self.assertEqual(result.get('days'), 5)
        self.assertEqual(result.get('remaining'), 3)
        self.assertEqual(result.get('remaining_after'), -2)
        self.assertTrue(result.get('exceeds'))

    def test_08_half_day_request(self):
        half_type = self.env['hr.leave.type'].create({
            'name': 'Portal Half Day',
            'requires_allocation': 'no',
            'leave_validation_type': 'hr',
            'request_unit': 'half_day',
        })
        self.authenticate('portal_employee', 'portal_employee')
        csrf = self._csrf_token(self.url_open('/my/leave/new').text)
        self.url_open('/my/leave/new', data={
            'csrf_token': csrf,
            'holiday_status_id': half_type.id,
            'request_unit_half': 'on',
            'request_date_from_period': 'pm',
            'request_date_from': '2026-07-08',
            'name': 'Afternoon off',
        })
        leave = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee.id),
            ('name', '=', 'Afternoon off'),
        ])
        self.assertEqual(len(leave), 1)
        self.assertTrue(leave.request_unit_half)
        self.assertEqual(leave.request_date_from_period, 'pm')
        self.assertEqual(leave.number_of_days, 0.5)

    def test_09_half_day_refused_for_full_day_type(self):
        self.authenticate('portal_employee', 'portal_employee')
        csrf = self._csrf_token(self.url_open('/my/leave/new').text)
        resp = self.url_open('/my/leave/new', data={
            'csrf_token': csrf,
            'holiday_status_id': self.leave_type.id,  # request_unit = day
            'request_unit_half': 'on',
            'request_date_from': '2026-07-09',
            'name': 'Not allowed half',
        })
        self.assertIn('cannot be taken in half days', resp.text)
        self.assertFalse(self.env['hr.leave'].search([('name', '=', 'Not allowed half')]))

    def test_10_supporting_document_and_detail(self):
        approver = self.env['res.users'].create({
            'name': 'Leave Approver',
            'login': 'leave_approver',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.employee.leave_manager_id = approver
        sick_type = self.env['hr.leave.type'].create({
            'name': 'Portal Sick',
            'requires_allocation': 'no',
            'leave_validation_type': 'manager',
            'support_document': True,
        })
        self.authenticate('portal_employee', 'portal_employee')
        csrf = self._csrf_token(self.url_open('/my/leave/new').text)
        self.url_open('/my/leave/new', data={
            'csrf_token': csrf,
            'holiday_status_id': sick_type.id,
            'request_date_from': '2026-07-20',
            'request_date_to': '2026-07-21',
            'name': 'Flu',
        }, files={'attachment': ('sick_note.pdf', b'%PDF-1.4 test', 'application/pdf')})

        leave = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee.id), ('name', '=', 'Flu')])
        self.assertEqual(len(leave), 1)
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'hr.leave'), ('res_id', '=', leave.id)])
        self.assertEqual(attachment.name, 'sick_note.pdf')

        detail = self.url_open('/my/leave/%s' % leave.id)
        self.assertEqual(detail.status_code, 200)
        self.assertIn('Waiting for Leave Approver', detail.text)
        self.assertIn('sick_note.pdf', detail.text)
        self.assertIn('access_token=', detail.text)

    def test_11_rejects_disallowed_file_type(self):
        self.authenticate('portal_employee', 'portal_employee')
        csrf = self._csrf_token(self.url_open('/my/leave/new').text)
        resp = self.url_open('/my/leave/new', data={
            'csrf_token': csrf,
            'holiday_status_id': self.leave_type.id,
            'request_date_from': '2026-07-22',
            'request_date_to': '2026-07-22',
            'name': 'Bad file',
        }, files={'attachment': ('script.exe', b'MZ', 'application/octet-stream')})
        self.assertIn('must be a PDF, JPG or PNG', resp.text)
        self.assertFalse(self.env['hr.leave'].search([('name', '=', 'Bad file')]))

    def test_12_allocations_page_lists_balance(self):
        alloc_type = self.env['hr.leave.type'].create({
            'name': 'Portal Annual Balance',
            'requires_allocation': 'yes',
            'leave_validation_type': 'hr',
        })
        allocation = self.env['hr.leave.allocation'].create({
            'name': 'Annual balance 2026',
            'employee_id': self.employee.id,
            'holiday_status_id': alloc_type.id,
            'number_of_days': 7,
            'date_from': '2026-01-01',
        })
        allocation.action_approve()
        self.authenticate('portal_employee', 'portal_employee')
        resp = self.url_open('/my/leaves/allocations')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Portal Annual Balance', resp.text)
        self.assertNotIn('no allocated leave types', resp.text)
