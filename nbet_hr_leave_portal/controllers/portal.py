# -*- coding: utf-8 -*-
import base64
import logging
import os
from datetime import datetime, time, timedelta

import pytz

from odoo import http, fields
from odoo.http import request
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

_logger = logging.getLogger(__name__)

# Supporting documents (e.g. sick notes) accepted from the portal form.
ATTACHMENT_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
ATTACHMENT_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
# Leave types that may be requested in half days.
HALF_DAY_UNITS = ('half_day', 'hour')
# How far ahead to list public holidays next to the request form.
PUBLIC_HOLIDAY_DAYS_AHEAD = 90


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
        """Active leave types evaluated in the context of this employee.

        Restrict to the employee's company (plus company-shared types) so the
        allocation computation is not evaluated against unrelated-company
        records.
        """
        company = employee.company_id
        domain = ['|', ('company_id', '=', False),
                  ('company_id', '=', company.id)] if company else []
        return request.env['hr.leave.type'].sudo().with_context(
            employee_id=employee.id).search(domain)

    def _leave_domain(self, employee):
        return [('employee_id', '=', employee.id)]

    def _remaining_for_type(self, leave_type, employee):
        """Remaining days (incl. pending requests) for an allocation-based type.

        Returns None for types that do not use allocations, or when Odoo cannot
        compute the figure for this type (logged, never raised to the user).
        """
        if leave_type.requires_allocation != 'yes':
            return None
        try:
            return leave_type.with_context(
                employee_id=employee.id).virtual_remaining_leaves
        except Exception:
            _logger.exception(
                "Could not compute remaining leave for type %s and employee %s",
                leave_type.id, employee.id)
            return None

    def _get_public_holidays(self, employee):
        """Upcoming public holidays for the employee's company/calendar,
        expressed as local dates in the employee's timezone."""
        tz = pytz.timezone(employee.tz or 'UTC')
        start = datetime.combine(fields.Date.context_today(employee), time.min)
        end = start + timedelta(days=PUBLIC_HOLIDAY_DAYS_AHEAD)
        holidays = employee.sudo().with_company(employee.company_id)._get_public_holidays(
            start, end).sorted('date_from')
        result = []
        for holiday in holidays:
            date_from = pytz.utc.localize(holiday.date_from).astimezone(tz).date()
            date_to = pytz.utc.localize(holiday.date_to).astimezone(tz).date()
            result.append({
                'name': holiday.name,
                'date_from': date_from,
                'date_to': date_to if date_to != date_from else False,
            })
        return result

    def _compute_request_days(self, employee, leave_type, date_from, date_to,
                              half_day=False, period='am'):
        """Duration in days, computed exactly as Odoo will store it, by
        evaluating an unsaved hr.leave for this employee."""
        vals = {
            'employee_id': employee.id,
            'holiday_status_id': leave_type.id,
            'request_date_from': date_from,
            'request_date_to': date_from if half_day else date_to,
        }
        if half_day:
            vals.update({
                'request_unit_half': True,
                'request_date_from_period': period if period in ('am', 'pm') else 'am',
            })
        draft = request.env['hr.leave'].sudo().with_company(
            employee.company_id).new(vals)
        return draft.number_of_days

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
            # Computing the allocation figures relies on hr.leave.type's
            # computed fields (``_compute_leaves``), which evaluate the
            # current employee context and can raise for an individual type
            # (e.g. accruals, multi-company data).  Guard each type so one
            # bad record degrades gracefully instead of returning a blank
            # 500 for the whole page, and log the real traceback so the root
            # cause stays visible in the server log.
            try:
                if leave_type.requires_allocation != 'yes':
                    continue
                # Odoo 18 dropped hr.leave.type.remaining_leaves; derive it.
                allocated = leave_type.max_leaves
                taken = leave_type.leaves_taken
                allocation_data.append({
                    'name': leave_type.display_name,
                    'allocated': allocated,
                    'taken': taken,
                    'remaining': allocated - taken,
                    'virtual_remaining': leave_type.virtual_remaining_leaves,
                })
            except Exception:
                _logger.exception(
                    "Could not compute leave allocation for leave type %s "
                    "and employee %s on the portal allocations page",
                    leave_type.id, employee.id)
                continue

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
        form = {k: v for k, v in post.items() if k != 'attachment'}
        values = {
            'employee': employee,
            'leave_types': leave_types,
            'half_day_units': HALF_DAY_UNITS,
            'public_holidays': self._get_public_holidays(employee),
            'page_name': 'leave_new',
            'form': form,
        }

        if request.httprequest.method == 'POST':
            upload = post.get('attachment')
            error = (self._validate_leave_form(post, leave_types)
                     or self._validate_attachment(upload))
            if not error:
                try:
                    leave = self._create_leave(employee, post, upload=upload)
                    return request.redirect('/my/leave/%s?message=created' % leave.id)
                except (UserError, ValidationError) as e:
                    error = e.args[0] if e.args else str(e)
                except Exception:
                    _logger.exception("Portal leave request failed for employee %s", employee.id)
                    error = "We could not register your request. Please check the dates and try again."

        values['error'] = error
        return request.render('nbet_hr_leave_portal.portal_leave_new', values)

    def _is_half_day(self, post):
        return post.get('request_unit_half') in ('on', 'true', '1', True)

    def _validate_leave_form(self, post, leave_types):
        if not post.get('holiday_status_id'):
            return "Please choose a time off type."
        leave_type = leave_types.filtered(
            lambda t: str(t.id) == str(post.get('holiday_status_id')))
        if not leave_type:
            return "The selected time off type is not available."
        half_day = self._is_half_day(post)
        if half_day and leave_type.request_unit not in HALF_DAY_UNITS:
            return "This time off type cannot be taken in half days."
        if not post.get('request_date_from') or (
                not half_day and not post.get('request_date_to')):
            return "Please provide both a start and an end date."
        try:
            date_from = fields.Date.from_string(post.get('request_date_from'))
            date_to = (date_from if half_day
                       else fields.Date.from_string(post.get('request_date_to')))
        except Exception:
            return "The dates provided are not valid."
        if date_to < date_from:
            return "The end date cannot be earlier than the start date."
        return None

    def _validate_attachment(self, upload):
        if not upload or not getattr(upload, 'filename', None):
            return None
        ext = os.path.splitext(upload.filename)[1].lower()
        if ext not in ATTACHMENT_EXTENSIONS:
            return "Supporting documents must be a PDF, JPG or PNG file."
        upload.stream.seek(0, os.SEEK_END)
        size = upload.stream.tell()
        upload.stream.seek(0)
        if size > ATTACHMENT_MAX_SIZE:
            return "Supporting documents must be smaller than 10 MB."
        return None

    def _create_leave(self, employee, post, upload=None):
        half_day = self._is_half_day(post)
        vals = {
            'name': post.get('name') or False,
            'employee_id': employee.id,
            'holiday_status_id': int(post.get('holiday_status_id')),
            'request_date_from': post.get('request_date_from'),
            'request_date_to': (post.get('request_date_from') if half_day
                                else post.get('request_date_to')),
        }
        if half_day:
            vals.update({
                'request_unit_half': True,
                'request_date_from_period': (
                    post.get('request_date_from_period')
                    if post.get('request_date_from_period') in ('am', 'pm') else 'am'),
            })
        leave = request.env['hr.leave'].sudo().with_context(
            mail_create_nosubscribe=True).create(vals)
        if upload and getattr(upload, 'filename', None):
            request.env['ir.attachment'].sudo().create({
                'name': upload.filename,
                'datas': base64.b64encode(upload.read()),
                'res_model': 'hr.leave',
                'res_id': leave.id,
            })
        # Move the request out of draft so it reaches the approver, mirroring
        # what the backend "Confirm" button does.
        if leave.state == 'draft' and hasattr(leave, 'action_confirm'):
            leave.action_confirm()
        return leave

    # ------------------------------------------------------------------
    # Live duration / balance preview for the request form (JSON)
    # ------------------------------------------------------------------
    @http.route(['/my/leave/preview'], type='json', auth='user', website=True)
    def portal_leave_preview(self, holiday_status_id=None, date_from=None,
                             date_to=None, half_day=False, period='am', **kw):
        employee = self._get_employee()
        if not employee or not holiday_status_id:
            return {}
        leave_type = self._get_leave_types(employee).filtered(
            lambda t: str(t.id) == str(holiday_status_id))
        if not leave_type:
            return {'error': "The selected time off type is not available."}

        remaining = self._remaining_for_type(leave_type, employee)
        result = {
            'requires_allocation': leave_type.requires_allocation == 'yes',
            'allows_half_day': leave_type.request_unit in HALF_DAY_UNITS,
            'support_document': leave_type.support_document,
            'remaining': remaining,
        }
        half_day = bool(half_day) and result['allows_half_day']
        try:
            d_from = fields.Date.from_string(date_from) if date_from else None
            d_to = d_from if half_day else (
                fields.Date.from_string(date_to) if date_to else None)
        except Exception:
            return dict(result, error="The dates provided are not valid.")
        if not d_from or not d_to:
            return result
        if d_to < d_from:
            return dict(result, error="The end date cannot be earlier than the start date.")

        try:
            days = self._compute_request_days(
                employee, leave_type, d_from, d_to, half_day=half_day, period=period)
        except Exception:
            _logger.exception("Could not preview leave duration for employee %s", employee.id)
            return dict(result, error="Could not calculate the duration for these dates.")

        result['days'] = days
        if remaining is not None:
            result['remaining_after'] = remaining - days
            result['exceeds'] = days > remaining
        return result

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
            'approver_label': self._approver_label(leave),
            'attachments': self._portal_attachments(leave),
        }
        return request.render('nbet_hr_leave_portal.portal_leave_detail', values)

    def _approver_label(self, leave):
        """Who approved/refused the request, or who it is waiting on."""
        if leave.state in ('validate', 'validate1', 'refuse'):
            approver = leave.second_approver_id or leave.first_approver_id
            if approver:
                verb = 'Refused by' if leave.state == 'refuse' else 'Approved by'
                return '%s %s' % (verb, approver.name)
        manager = leave.employee_id.leave_manager_id
        if leave.state == 'confirm' and manager:
            return 'Waiting for %s' % manager.name
        return False

    def _portal_attachments(self, leave):
        """Attachments of the leave with tokenised download URLs, since
        portal users have no read access to hr.leave attachments directly."""
        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'hr.leave'),
            ('res_id', '=', leave.id),
        ])
        result = []
        for attachment in attachments:
            token = attachment.access_token or attachment.generate_access_token()[0]
            result.append({
                'name': attachment.name,
                'url': '/web/content/%s?access_token=%s&download=true' % (
                    attachment.id, token),
            })
        return result

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
