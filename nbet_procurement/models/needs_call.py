# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class NeedsCall(models.Model):
    """Annual, fiscal-year-wide call for procurement needs.

    The Procurement Department opens one Needs Call per fiscal year. Every
    department is required to submit its procurement needs (as a
    ``nbet.needs.assessment``) against the open call. The call tracks which
    departments have/have not submitted and consolidates the approved
    submissions into the eventual Procurement Plan.
    """
    _name = 'nbet.needs.call'
    _description = 'Annual Procurement Needs Call'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'fiscal_year desc, create_date desc'

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    fiscal_year = fields.Char(required=True, tracking=True)
    date_open = fields.Date(string='Date Opened', tracking=True)
    submission_deadline = fields.Date(tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open for Submissions'),
        ('closed', 'Closed'),
        ('consolidated', 'Consolidated'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True)
    instructions = fields.Html(
        help='Guidance issued to departments on how to submit their needs.',
    )

    department_line_ids = fields.One2many(
        'nbet.needs.call.department', 'call_id', string='Departments',
    )
    assessment_ids = fields.One2many(
        'nbet.needs.assessment', 'call_id', string='Submissions',
    )
    procurement_plan_id = fields.Many2one(
        'nbet.procurement.plan', string='Procurement Plan', readonly=True, copy=False,
    )

    total_departments = fields.Integer(compute='_compute_stats', store=True)
    submitted_count = fields.Integer(
        string='Submitted', compute='_compute_stats', store=True,
    )
    pending_count = fields.Integer(
        string='Pending', compute='_compute_stats', store=True,
    )
    approved_count = fields.Integer(
        string='Approved', compute='_compute_stats', store=True,
    )
    submission_rate = fields.Float(
        string='Submission Rate', compute='_compute_stats', store=True,
        help='Share of departments that have submitted their needs.',
    )
    total_estimated = fields.Float(
        string='Total Estimated (NGN)', compute='_compute_stats', store=True,
    )
    assessment_count = fields.Integer(compute='_compute_stats')

    _sql_constraints = [
        ('fiscal_year_uniq', 'unique(fiscal_year)',
         'A Needs Call already exists for this fiscal year.'),
    ]

    @api.depends(
        'department_line_ids.status',
        'department_line_ids.total_estimated',
        'assessment_ids',
    )
    def _compute_stats(self):
        for call in self:
            lines = call.department_line_ids
            submitted = lines.filtered(lambda l: l.status != 'pending')
            approved = lines.filtered(lambda l: l.status == 'approved')
            call.total_departments = len(lines)
            call.submitted_count = len(submitted)
            call.approved_count = len(approved)
            call.pending_count = len(lines) - len(submitted)
            call.submission_rate = (
                (len(submitted) / len(lines)) if lines else 0.0
            )
            call.total_estimated = sum(lines.mapped('total_estimated'))
            call.assessment_count = len(call.assessment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nbet.needs.call') or 'New'
        return super().create(vals_list)

    def action_open(self):
        """Open the call and require every active department to submit."""
        for call in self:
            call._sync_departments()
            call.write({
                'state': 'open',
                'date_open': call.date_open or fields.Date.context_today(call),
            })
            call._notify_departments()

    def _notify_departments(self):
        """Give every department a draft submission, an activity, and an email
        with a direct link to fill in their procurement needs."""
        self.ensure_one()
        Assessment = self.env['nbet.needs.assessment']
        deadline = self.submission_deadline or fields.Date.context_today(self)
        for line in self.department_line_ids:
            dept = line.department_id
            assessment = line.assessment_id
            if not assessment:
                manager_user = dept.manager_id.user_id
                assessment = Assessment.create({
                    'call_id': self.id,
                    'department_id': dept.id,
                    'fiscal_year': self.fiscal_year,
                    'requested_by': (manager_user or self.env.user).id,
                })
            if assessment.state != 'draft':
                # Department has already submitted; don't nag them.
                continue
            user = dept.manager_id.user_id
            if not user:
                # No department head user to notify; procurement will follow up.
                continue
            assessment.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Submit %s procurement needs', self.fiscal_year),
                note=_(
                    'Your department is required to submit its procurement '
                    'needs for the %(year)s fiscal year to the Procurement '
                    'Department. Please add your items and click Submit.',
                    year=self.fiscal_year,
                ),
                user_id=user.id,
                date_deadline=deadline,
            )
            due = _(' before %s', deadline) if self.submission_deadline else ''
            assessment.message_notify(
                partner_ids=user.partner_id.ids,
                subject=_('Procurement Needs Call %s', self.fiscal_year),
                body=_(
                    '<p>Dear %(name)s,</p>'
                    '<p>The Procurement Department has opened needs call '
                    '<strong>%(call)s</strong> for the <strong>%(year)s</strong> '
                    'fiscal year. All departments are required to submit their '
                    'procurement needs and requirements.</p>'
                    '<p>Please open the submission below, add your department\'s '
                    'items and click <strong>Submit</strong>%(due)s.</p>',
                    name=user.name, call=self.name,
                    year=self.fiscal_year, due=due,
                ),
            )

    def action_sync_departments(self):
        """Refresh the department checklist (add newly created departments)."""
        for call in self:
            call._sync_departments()

    def _sync_departments(self):
        self.ensure_one()
        existing = self.department_line_ids.mapped('department_id')
        departments = self.env['hr.department'].search([])
        missing = departments - existing
        if missing:
            self.env['nbet.needs.call.department'].create([
                {'call_id': self.id, 'department_id': dept.id}
                for dept in missing
            ])

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reopen(self):
        self.write({'state': 'open'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_generate_plan(self):
        """Consolidate approved submissions into a Procurement Plan."""
        self.ensure_one()
        if self.procurement_plan_id:
            raise UserError(
                "A Procurement Plan has already been generated for this call.")
        approved = self.assessment_ids.filtered(
            lambda a: a.state == 'approved')
        if not approved:
            raise UserError(
                "No approved submissions to consolidate. Approve the "
                "departments' needs assessments first.")
        plan = self.env['nbet.procurement.plan'].create({
            'fiscal_year': self.fiscal_year,
            'call_id': self.id,
            'assessment_ids': [(6, 0, approved.ids)],
        })
        plan.action_populate_from_assessments()
        self.write({
            'state': 'consolidated',
            'procurement_plan_id': plan.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Procurement Plan',
            'res_model': 'nbet.procurement.plan',
            'res_id': plan.id,
            'view_mode': 'form',
        }

    def action_view_plan(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Procurement Plan',
            'res_model': 'nbet.procurement.plan',
            'res_id': self.procurement_plan_id.id,
            'view_mode': 'form',
        }

    def action_view_submissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Submissions',
            'res_model': 'nbet.needs.assessment',
            'domain': [('call_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {
                'default_call_id': self.id,
                'default_fiscal_year': self.fiscal_year,
            },
        }


class NeedsCallDepartment(models.Model):
    """Per-department submission tracker within a Needs Call."""
    _name = 'nbet.needs.call.department'
    _description = 'Needs Call Department Submission'
    _order = 'department_id'

    call_id = fields.Many2one(
        'nbet.needs.call', required=True, ondelete='cascade', index=True,
    )
    department_id = fields.Many2one(
        'hr.department', string='Department', required=True,
    )
    manager_id = fields.Many2one(
        related='department_id.manager_id', string='Department Head',
    )
    assessment_id = fields.Many2one(
        'nbet.needs.assessment', string='Submission',
        compute='_compute_submission', store=True,
    )
    status = fields.Selection([
        ('pending', 'Not Submitted'),
        ('submitted', 'Submitted'),
        ('reviewed', 'Reviewed'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], compute='_compute_submission', store=True, default='pending')
    total_estimated = fields.Float(
        string='Estimated (NGN)', compute='_compute_submission', store=True,
    )
    line_count = fields.Integer(
        string='Items', compute='_compute_submission', store=True,
    )

    _sql_constraints = [
        ('call_department_uniq', 'unique(call_id, department_id)',
         'Each department appears only once per Needs Call.'),
    ]

    @api.depends(
        'call_id.assessment_ids',
        'call_id.assessment_ids.state',
        'call_id.assessment_ids.department_id',
        'call_id.assessment_ids.total_estimated',
    )
    def _compute_submission(self):
        for line in self:
            assessment = line.call_id.assessment_ids.filtered(
                lambda a: a.department_id == line.department_id
            )[:1]
            line.assessment_id = assessment
            if assessment:
                # A draft (started but not yet submitted) still counts as pending.
                line.status = (
                    'pending' if assessment.state == 'draft' else assessment.state
                )
                line.total_estimated = assessment.total_estimated
                line.line_count = len(assessment.line_ids)
            else:
                line.status = 'pending'
                line.total_estimated = 0.0
                line.line_count = 0

    def action_open_assessment(self):
        """Open the submission, or start a new one for this department."""
        self.ensure_one()
        if self.assessment_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'nbet.needs.assessment',
                'res_id': self.assessment_id.id,
                'view_mode': 'form',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Submit Needs',
            'res_model': 'nbet.needs.assessment',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_call_id': self.call_id.id,
                'default_fiscal_year': self.call_id.fiscal_year,
                'default_department_id': self.department_id.id,
            },
        }
