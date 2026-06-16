# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


# Human readable labels for the hr.leave workflow states.
LEAVE_STATE_LABELS = {
    'draft': 'To Submit',
    'confirm': 'To Approve',
    'validate1': 'Second Approval',
    'validate': 'Approved',
    'refuse': 'Refused',
}

# Bootstrap badge colour per state, used in the templates.
LEAVE_STATE_BADGES = {
    'draft': 'secondary',
    'confirm': 'warning',
    'validate1': 'info',
    'validate': 'success',
    'refuse': 'danger',
}


class LeavePortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_employee(self):
        """Return the hr.employee linked to the current portal user (sudo)."""
        user = request.env.user
        return request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1)

    def _get_leave_types(self, employee):
        """Active leave types evaluated in the context of this employee."""
        return request.env['hr.leave.type'].sudo().with_context(
            employee_id=employee.id).search([])

    def _leave_domain(self, employee):
        return [('employee_id', '=', employee.id)]

    # ------------------------------------------------------------------
    # Portal home counter
    # ------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'leave_count' in counters:
            employee = self._get_employee()
            values['leave_count'] = request.env['hr.leave'].sudo().search_count(
                self._leave_domain(employee)) if employee else 0
        return values

    # ------------------------------------------------------------------
    # List of leave requests
    # ------------------------------------------------------------------
    @http.route(['/my/leaves', '/my/leaves/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_leaves(self, page=1, sortby=None, **kw):
        employee = self._get_employee()
        if not employee:
            return request.render('nbet_hr_leave_portal.portal_leave_no_employee', {
                'page_name': 'leave',
            })

        Leave = request.env['hr.leave'].sudo()
        domain = self._leave_domain(employee)

        searchbar_sortings = {
            'date': {'label': 'Newest', 'order': 'request_date_from desc'},
            'state': {'label': 'Status', 'order': 'state'},
            'type': {'label': 'Type', 'order': 'holiday_status_id'},
        }
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        leave_count = Leave.search_count(domain)
        pager = portal_pager(
            url='/my/leaves',
            url_args={'sortby': sortby},
            total=leave_count,
            page=page,
            step=self._items_per_page,
        )
        leaves = Leave.search(
            domain, order=order, limit=self._items_per_page, offset=pager['offset'])

        values = {
            'employee': employee,
            'leaves': leaves,
            'page_name': 'leave',
            'pager': pager,
            'sortby': sortby,
            'searchbar_sortings': searchbar_sortings,
            'default_url': '/my/leaves',
            'state_labels': LEAVE_STATE_LABELS,
            'state_badges': LEAVE_STATE_BADGES,
        }
        return request.render('nbet_hr_leave_portal.portal_my_leaves', values)

    # ------------------------------------------------------------------
    # Remaining allocations
    # ------------------------------------------------------------------
    @http.route(['/my/leaves/allocations'], type='http', auth='user', website=True)
    def portal_my_allocations(self, **kw):
        employee = self._get_employee()
        if not employee:
            return request.render('nbet_hr_leave_portal.portal_leave_no_employee', {
                'page_name': 'leave_allocation',
            })

        allocation_data = []
        for leave_type in self._get_leave_types(employee):
            if leave_type.requires_allocation != 'yes':
                continue
            allocation_data.append({
                'name': leave_type.display_name,
                'allocated': leave_type.max_leaves,
                'taken': leave_type.leaves_taken,
                'remaining': leave_type.remaining_leaves,
                'virtual_remaining': leave_type.virtual_remaining_leaves,
            })

        values = {
            'employee': employee,
            'allocation_data': allocation_data,
            'page_name': 'leave_allocation',
        }
        return request.render('nbet_hr_leave_portal.portal_my_allocations', values)

    # ------------------------------------------------------------------
    # New leave request
    # ------------------------------------------------------------------
    @http.route(['/my/leave/new'], type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def portal_leave_new(self, **post):
        employee = self._get_employee()
        if not employee:
            return request.render('nbet_hr_leave_portal.portal_leave_no_employee', {
                'page_name': 'leave',
            })

        leave_types = self._get_leave_types(employee)
        error = None
        values = {
            'employee': employee,
            'leave_types': leave_types,
            'page_name': 'leave_new',
            'form': post,
        }

        if request.httprequest.method == 'POST':
            error = self._validate_leave_form(post, leave_types)
            if not error:
                try:
                    leave = self._create_leave(employee, post)
                    return request.redirect('/my/leave/%s?message=created' % leave.id)
                except (UserError, ValidationError) as e:
                    error = e.args[0] if e.args else str(e)
                except Exception:
                    error = "We could not register your request. Please check the dates and try again."

        values['error'] = error
        return request.render('nbet_hr_leave_portal.portal_leave_new', values)

    def _validate_leave_form(self, post, leave_types):
        if not post.get('holiday_status_id'):
            return "Please choose a time off type."
        if str(post.get('holiday_status_id')) not in [str(t.id) for t in leave_types]:
            return "The selected time off type is not available."
        if not post.get('request_date_from') or not post.get('request_date_to'):
            return "Please provide both a start and an end date."
        try:
            date_from = fields.Date.from_string(post.get('request_date_from'))
            date_to = fields.Date.from_string(post.get('request_date_to'))
        except Exception:
            return "The dates provided are not valid."
        if date_to < date_from:
            return "The end date cannot be earlier than the start date."
        return None

    def _create_leave(self, employee, post):
        vals = {
            'name': post.get('name') or False,
            'employee_id': employee.id,
            'holiday_status_id': int(post.get('holiday_status_id')),
            'request_date_from': post.get('request_date_from'),
            'request_date_to': post.get('request_date_to'),
        }
        leave = request.env['hr.leave'].sudo().with_context(
            mail_create_nosubscribe=True).create(vals)
        # Move the request out of draft so it reaches the approver, mirroring
        # what the backend "Confirm" button does.
        if leave.state == 'draft' and hasattr(leave, 'action_confirm'):
            leave.action_confirm()
        return leave

    # ------------------------------------------------------------------
    # Single leave request detail
    # ------------------------------------------------------------------
    @http.route(['/my/leave/<int:leave_id>'], type='http', auth='user', website=True)
    def portal_leave_detail(self, leave_id, message=None, **kw):
        employee = self._get_employee()
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not employee or not leave.exists() or leave.employee_id != employee:
            return request.redirect('/my/leaves')

        values = {
            'employee': employee,
            'leave': leave,
            'page_name': 'leave',
            'message': message,
            'state_labels': LEAVE_STATE_LABELS,
            'state_badges': LEAVE_STATE_BADGES,
            'can_cancel': leave.state in ('draft', 'confirm'),
        }
        return request.render('nbet_hr_leave_portal.portal_leave_detail', values)

    # ------------------------------------------------------------------
    # Cancel a pending request
    # ------------------------------------------------------------------
    @http.route(['/my/leave/<int:leave_id>/cancel'], type='http', auth='user',
                website=True, methods=['POST'])
    def portal_leave_cancel(self, leave_id, **kw):
        employee = self._get_employee()
        leave = request.env['hr.leave'].sudo().browse(leave_id)
        if not employee or not leave.exists() or leave.employee_id != employee:
            return request.redirect('/my/leaves')

        if leave.state in ('draft', 'confirm'):
            try:
                leave.unlink()
                return request.redirect('/my/leaves?message=cancelled')
            except (UserError, AccessError):
                return request.redirect('/my/leave/%s?message=cancel_error' % leave_id)
        return request.redirect('/my/leave/%s' % leave_id)
