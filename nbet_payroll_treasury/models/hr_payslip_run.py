# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

# Payslips that a treasury payment actually covers. Draft and cancelled slips
# are not payable, and are left out of every total below.
PAYABLE_STATES = ('done', 'paid')


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    approval_state = fields.Selection([
        ('none', 'Not Submitted'),
        ('md_approval', 'Pending MD Approval'),
        ('md_approved', 'MD Approved'),
        ('treasury', 'With Treasury'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
    ], string='Payment Approval', default='none', required=True,
        copy=False, tracking=True, index=True)

    submitted_by_id = fields.Many2one(
        'res.users', string='Submitted By', readonly=True, copy=False,
    )
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)

    md_approver_id = fields.Many2one(
        'res.users', string='Approved By (MD)', readonly=True, copy=False, tracking=True,
    )
    md_approval_date = fields.Datetime(string='MD Approval Date', readonly=True, copy=False)
    md_notes = fields.Text(string='MD Notes')

    rejection_reason = fields.Text(string='Rejection Reason', copy=False)
    rejected_by_id = fields.Many2one('res.users', string='Rejected By', readonly=True, copy=False)
    rejection_date = fields.Datetime(string='Rejected On', readonly=True, copy=False)

    treasury_submitted_by_id = fields.Many2one(
        'res.users', string='Sent to Treasury By', readonly=True, copy=False,
    )
    treasury_submitted_date = fields.Datetime(
        string='Sent to Treasury On', readonly=True, copy=False,
    )

    payment_schedule_id = fields.Many2one(
        'nbet.payment.schedule',
        string='Payment Schedule',
        readonly=True,
        copy=False,
        index='btree_not_null',
    )
    schedule_state = fields.Selection(
        related='payment_schedule_id.state', string='Treasury Status', readonly=True,
    )
    voucher_count = fields.Integer(compute='_compute_voucher_count')

    payable_payslip_count = fields.Integer(compute='_compute_payroll_totals')
    payroll_net_total = fields.Monetary(
        string='Net Salaries', compute='_compute_payroll_totals',
    )
    payroll_deduction_total = fields.Monetary(
        string='Statutory Deductions', compute='_compute_payroll_totals',
    )
    payroll_total = fields.Monetary(
        string='Total Payroll Cost', compute='_compute_payroll_totals',
        help='Net salaries plus the statutory deductions to be remitted - what '
             'the treasury is asked to disburse for this batch.',
    )

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------
    def _treasury_payslips(self):
        """The payslips of this batch that the treasury will pay.

        Sudo'd: the MD approving the batch and the treasury paying it both need
        these figures without being payroll users.
        """
        self.ensure_one()
        return self.sudo().slip_ids.filtered(lambda s: s.state in PAYABLE_STATES)

    def _deduction_amounts(self):
        """[(rule, amount)] withheld across this batch, skipping the empty ones."""
        self.ensure_one()
        payslips = self._treasury_payslips()
        if not payslips:
            return []
        precision = self.currency_id.rounding or 0.01
        amounts = []
        rules = self.env['nbet.payroll.deduction.rule'].sudo()._rules_for_company(self.company_id)
        for rule in rules:
            amount = rule._amount_for_payslips(payslips)
            if not float_is_zero(amount, precision_rounding=precision):
                amounts.append((rule, amount))
        return amounts

    @api.depends('slip_ids.state', 'slip_ids.net_wage', 'slip_ids.line_ids.total')
    def _compute_payroll_totals(self):
        for run in self:
            payslips = run._treasury_payslips()
            run.payable_payslip_count = len(payslips)
            run.payroll_net_total = sum(payslips.mapped('net_wage'))
            run.payroll_deduction_total = sum(
                amount for _rule, amount in run._deduction_amounts()
            )
            run.payroll_total = run.payroll_net_total + run.payroll_deduction_total

    @api.depends('payment_schedule_id.voucher_ids')
    def _compute_voucher_count(self):
        for run in self:
            run.voucher_count = len(run.payment_schedule_id.voucher_ids)

    # ------------------------------------------------------------------
    # MD approval
    # ------------------------------------------------------------------
    def action_submit_to_md(self):
        for run in self:
            if run.approval_state not in ('none', 'rejected'):
                raise UserError(
                    "%s has already been submitted for approval." % run.name
                )
            if not run._are_payslips_ready():
                raise UserError(
                    "Validate the payslips of %s before submitting the batch for "
                    "approval." % run.name
                )
            if not run._treasury_payslips():
                raise UserError("%s has no validated payslip to pay." % run.name)
            run.write({
                'approval_state': 'md_approval',
                'submitted_by_id': self.env.user.id,
                'submitted_date': fields.Datetime.now(),
                'rejection_reason': False,
                'rejected_by_id': False,
                'rejection_date': False,
            })
            run.message_post(
                body="Payroll batch submitted to the Managing Director for approval "
                     "by %s: %s payslip(s), %s net, %s deductions."
                     % (self.env.user.display_name, run.payable_payslip_count,
                        run.payroll_net_total, run.payroll_deduction_total)
            )

    def action_md_approve(self):
        for run in self:
            if run.approval_state != 'md_approval':
                raise UserError(
                    "%s is not awaiting MD approval." % run.name
                )
            run.write({
                'approval_state': 'md_approved',
                'md_approver_id': self.env.user.id,
                'md_approval_date': fields.Datetime.now(),
            })
            run.message_post(
                body="Payroll batch approved by the Managing Director (%s)."
                     % self.env.user.display_name
            )

    def action_md_reject(self):
        for run in self:
            if run.approval_state != 'md_approval':
                raise UserError("%s is not awaiting MD approval." % run.name)
            if not run.rejection_reason:
                raise UserError(
                    "Enter the rejection reason on %s before rejecting it." % run.name
                )
            run.write({
                'approval_state': 'rejected',
                'rejected_by_id': self.env.user.id,
                'rejection_date': fields.Datetime.now(),
                'md_approver_id': False,
                'md_approval_date': False,
            })
            run.message_post(
                body="Payroll batch rejected by %s: %s"
                     % (self.env.user.display_name, run.rejection_reason)
            )

    # ------------------------------------------------------------------
    # Hand-over to treasury
    # ------------------------------------------------------------------
    def _check_ready_for_treasury(self):
        """Everything the treasury needs to raise a voucher per payslip."""
        self.ensure_one()
        payslips = self._treasury_payslips()
        if not payslips:
            raise UserError("%s has no validated payslip to pay." % self.name)

        missing_payee = payslips.filtered(lambda s: not s.employee_id.work_contact_id)
        if missing_payee:
            raise UserError(
                "These employees have no work contact, so no payee can be put on "
                "their voucher. Set one on the employee record first:\n%s"
                % '\n'.join(sorted(missing_payee.mapped('employee_id.name')))
            )

        precision = self.currency_id.rounding or 0.01
        non_positive = payslips.filtered(
            lambda s: float_compare(s.net_wage, 0.0, precision_rounding=precision) <= 0
        )
        if non_positive:
            raise UserError(
                "These payslips have no positive net pay, so they cannot be paid. "
                "Remove them from the batch or correct them:\n%s"
                % '\n'.join(sorted(non_positive.mapped('employee_id.name')))
            )

        # The remittance voucher clears its liability account, so every rule
        # actually being withheld needs one.
        no_account = [
            rule.name for rule, _amount in self._deduction_amounts()
            if not rule.tax_payable_account_id
        ]
        if no_account:
            raise UserError(
                "Set a Payable Account on these payroll deduction rules before "
                "sending the batch to treasury:\n%s" % '\n'.join(sorted(no_account))
            )

    def _prepare_payment_schedule_vals(self):
        self.ensure_one()
        deductions = self._deduction_amounts()
        return {
            'source_type': 'payroll',
            'payslip_run_id': self.id,
            'description': 'Payroll - %s' % self.name,
            'amount': self.payroll_total,
            'currency_id': self.currency_id.id,
            'tax_line_ids': [
                (0, 0, {
                    'name': rule.name,
                    'tax_type': rule.tax_type,
                    'rate': 0.0,
                    'base_amount': amount,
                    'amount': amount,
                    'tax_body_id': rule.partner_id.id,
                    'tax_payable_account_id': rule.tax_payable_account_id.id,
                    'payroll_deduction_rule_id': rule.id,
                })
                for rule, amount in deductions
            ],
        }

    def action_send_to_treasury(self):
        for run in self:
            if run.approval_state != 'md_approved':
                raise UserError(
                    "%s must be approved by the Managing Director before it goes to "
                    "treasury." % run.name
                )
            if run.payment_schedule_id:
                raise UserError(
                    "%s is already with treasury on payment schedule %s."
                    % (run.name, run.payment_schedule_id.name)
                )
            run._check_ready_for_treasury()
            # Payroll raises the schedule but does not work in treasury, so it
            # has no create rights of its own on the payment schedule.
            schedule = self.env['nbet.payment.schedule'].sudo().create(
                run._prepare_payment_schedule_vals()
            )
            run.write({
                'approval_state': 'treasury',
                'payment_schedule_id': schedule.id,
                'treasury_submitted_by_id': self.env.user.id,
                'treasury_submitted_date': fields.Datetime.now(),
            })
            run.message_post(
                body="Payroll batch sent to Treasury by %s on payment schedule %s "
                     "for a total of %s."
                     % (self.env.user.display_name, schedule.name, run.payroll_total)
            )
            schedule.message_post(
                body="Raised from payroll batch %s, approved by the Managing "
                     "Director (%s) on %s."
                     % (run.name, run.md_approver_id.display_name, run.md_approval_date)
            )

    # ------------------------------------------------------------------
    # Settlement, driven from the treasury vouchers
    # ------------------------------------------------------------------
    def _mark_paid_from_treasury(self):
        """Close the batch once every voucher raised against it has been paid."""
        self.ensure_one()
        unpaid = self._treasury_payslips().filtered(lambda s: s.state != 'paid')
        if unpaid:
            unpaid.with_context(nbet_treasury_settlement=True).action_payslip_paid()
        self.write({'approval_state': 'paid'})
        if self.state != 'paid':
            self.with_context(nbet_treasury_settlement=True).write({'state': 'paid'})

    def action_paid(self):
        """Payment is the treasury's to record once the batch is in the chain."""
        blocked = self.filtered(
            lambda r: r.approval_state in ('md_approval', 'md_approved', 'treasury')
        )
        if blocked and not self.env.context.get('nbet_treasury_settlement'):
            raise UserError(
                "%s is awaiting payment through Treasury. The batch is marked paid "
                "when its payment vouchers are paid, not from here."
                % ', '.join(blocked.mapped('name'))
            )
        return super().action_paid()

    def action_unpaid(self):
        paid_by_treasury = self.filtered(lambda r: r.approval_state == 'paid')
        if paid_by_treasury:
            raise UserError(
                "%s was paid through Treasury. Reverse the payment vouchers rather "
                "than reopening the batch here."
                % ', '.join(paid_by_treasury.mapped('name'))
            )
        return super().action_unpaid()

    def action_draft(self):
        for run in self:
            if run.approval_state not in ('none', 'rejected'):
                raise UserError(
                    "%s is in the payment approval chain (%s) and can no longer be "
                    "reset to draft. Reject it first."
                    % (run.name, dict(run._fields['approval_state'].selection)[run.approval_state])
                )
        return super().action_draft()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_view_payment_schedule(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payment Schedule',
            'res_model': 'nbet.payment.schedule',
            'res_id': self.payment_schedule_id.id,
            'view_mode': 'form',
        }

    def action_view_vouchers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payment Vouchers',
            'res_model': 'nbet.payment.voucher',
            'view_mode': 'list,form',
            'domain': [('schedule_id', '=', self.payment_schedule_id.id)],
        }
