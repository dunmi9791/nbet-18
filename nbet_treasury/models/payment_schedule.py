# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class PaymentSchedule(models.Model):
    _name = 'nbet.payment.schedule'
    _description = 'Payment Schedule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scheduled_date asc, priority desc, create_date desc'

    name = fields.Char(
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )
    source_type = fields.Selection(
        [('procurement', 'Procurement Payment Request')],
        string='Payment Source',
        default='procurement',
        required=True,
        readonly=True,
        help='What the treasury is being asked to pay. Other modules add their '
             'own sources, e.g. a payroll batch.',
    )
    payment_request_id = fields.Many2one(
        'nbet.payment.request',
        string='Payment Request',
        tracking=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Contractor/Vendor',
        compute='_compute_from_payment_request',
        store=True,
        readonly=False,
    )
    contract_award_id = fields.Many2one(
        'nbet.contract.award',
        string='Contract Award',
        related='payment_request_id.contract_award_id',
        store=True,
    )
    milestone_id = fields.Many2one(
        'nbet.contract.milestone',
        string='Milestone',
        related='payment_request_id.milestone_id',
        store=True,
    )
    description = fields.Char(
        compute='_compute_from_payment_request',
        store=True,
        readonly=False,
    )
    category = fields.Selection(
        related='payment_request_id.category',
        store=True,
    )
    amount = fields.Float(
        string='Payment Amount (NGN)',
        compute='_compute_from_payment_request',
        store=True,
        readonly=False,
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    transaction_reference = fields.Char(
        string='Transaction Reference',
        readonly=True,
        copy=False,
        index=True,
        help='Reference shared by every voucher raised for this payment.',
    )

    state = fields.Selection([
        ('pending', 'Pending'),
        ('scheduled', 'Scheduled'),
        ('cfo_approved', 'CFO Approved'),
        ('fm_approved', 'Finance Manager Approved'),
        ('voucher_generated', 'Vouchers Generated'),
        ('audit_pending', 'Pending Audit Review'),
        ('audit_reviewed', 'Audit Reviewed'),
        ('audited', 'Audited'),
        ('paid', 'Paid'),
        ('on_hold', 'On Hold'),
        ('cancelled', 'Cancelled'),
    ], default='pending', tracking=True)

    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'High'),
        ('2', 'Urgent'),
    ], default='0', tracking=True)

    scheduled_date = fields.Date(string='Scheduled Payment Date', tracking=True)
    payment_date = fields.Date(string='Actual Payment Date', tracking=True)
    payment_method = fields.Selection([
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('draft', 'Bank Draft'),
    ], string='Payment Method', tracking=True)
    payment_reference = fields.Char(string='Payment Reference', tracking=True)
    bank_account = fields.Char(string='Beneficiary Bank Account')
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        domain="[('type', 'in', ('bank', 'cash'))]",
        tracking=True,
        help='Default bank or cash journal for the vouchers raised on this payment. '
             'Each voucher can override it.',
    )

    treasury_officer_id = fields.Many2one('res.users', string='Treasury Officer', tracking=True)
    finance_officer_id = fields.Many2one(
        'res.users',
        string='Assigned Finance Officer',
        tracking=True,
        copy=False,
        help='Officer responsible for raising the payment vouchers once the '
             'Finance Manager has approved.',
    )

    # --- Approval chain: CFO -> Finance Manager -> Audit review -> Audit approval ---
    cfo_approved_by = fields.Many2one('res.users', string='CFO', tracking=True, copy=False)
    cfo_approval_date = fields.Datetime(string='CFO Approval Date & Time', copy=False)
    cfo_notes = fields.Text(string='CFO Notes')

    fm_approved_by = fields.Many2one('res.users', string='Finance Manager', tracking=True, copy=False)
    fm_approval_date = fields.Datetime(string='Finance Manager Approval Date & Time', copy=False)
    fm_notes = fields.Text(string='Finance Manager Notes')

    audit_reviewer_id = fields.Many2one(
        'res.users', string='Audit Reviewer', tracking=True, copy=False,
    )
    audit_review_date = fields.Datetime(string='Audit Review Date & Time', copy=False)
    audit_review_notes = fields.Text(string='Audit Review Notes')

    auditor_id = fields.Many2one(
        'res.users', string='Audit Approver', tracking=True, copy=False,
    )
    audit_date = fields.Datetime(string='Audit Approval Date & Time', copy=False)
    audit_notes = fields.Text(string='Audit Approval Notes')

    # --- Statutory deductions and vouchers ---
    tax_line_ids = fields.One2many(
        'nbet.payment.schedule.tax',
        'schedule_id',
        string='Statutory Deductions',
        copy=True,
    )
    tax_amount = fields.Float(
        string='Total Deductions (NGN)',
        compute='_compute_amounts',
        store=True,
    )
    net_amount = fields.Float(
        string='Net Payable to Vendor (NGN)',
        compute='_compute_amounts',
        store=True,
    )
    voucher_ids = fields.One2many(
        'nbet.payment.voucher',
        'schedule_id',
        string='Payment Vouchers',
    )
    voucher_count = fields.Integer(compute='_compute_voucher_count')

    hold_reason = fields.Text(string='Hold Reason')
    notes = fields.Html()

    @api.depends('payment_request_id', 'payment_request_id.vendor_id',
                 'payment_request_id.description', 'payment_request_id.requested_amount')
    def _compute_from_payment_request(self):
        """Carry the request's figures onto the schedule.

        A schedule raised from another source - a payroll batch, say - has no
        payment request, and fills these in itself, so leave those alone.
        """
        for rec in self:
            request = rec.payment_request_id
            if not request:
                rec.vendor_id = rec.vendor_id
                rec.description = rec.description
                rec.amount = rec.amount
                continue
            rec.vendor_id = request.vendor_id
            rec.description = request.description
            rec.amount = request.requested_amount

    @api.depends('amount', 'tax_line_ids.amount')
    def _compute_amounts(self):
        for rec in self:
            rec.tax_amount = sum(rec.tax_line_ids.mapped('amount'))
            rec.net_amount = rec.amount - rec.tax_amount

    @api.depends('voucher_ids')
    def _compute_voucher_count(self):
        data = self.env['nbet.payment.voucher']._read_group(
            [('schedule_id', 'in', self.ids)], ['schedule_id'], ['__count'],
        )
        counts = {schedule.id: count for schedule, count in data}
        for rec in self:
            rec.voucher_count = counts.get(rec.id, 0)

    @api.constrains('tax_line_ids', 'amount')
    def _check_deductions(self):
        for rec in self:
            precision = rec.currency_id.rounding or 0.01
            if float_compare(rec.tax_amount, rec.amount, precision_rounding=precision) > 0:
                raise ValidationError(
                    "Total statutory deductions (%s) cannot exceed the payment "
                    "amount (%s) on %s." % (rec.tax_amount, rec.amount, rec.name)
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nbet.payment.schedule') or 'New'
        schedules = super().create(vals_list)
        for rec in schedules:
            if not rec.tax_line_ids and rec._uses_default_deductions():
                rec._apply_default_deductions()
        return schedules

    def _source_document_name(self):
        """How the source of this payment is named in logs and vouchers."""
        self.ensure_one()
        return self.payment_request_id.name or self.name

    def _uses_default_deductions(self):
        """Whether the configured tax rules pre-fill this schedule's deductions.

        Only contract payments are deducted by rule; a payroll batch brings its
        own statutory deductions off the payslips.
        """
        self.ensure_one()
        return self.source_type == 'procurement'

    def _apply_default_deductions(self):
        """Pre-fill the statutory deductions from the configured tax rules."""
        self.ensure_one()
        rules = self.env['nbet.tax.rule']._rules_for_category(self.category)
        if not rules:
            return
        self.tax_line_ids = [(5, 0, 0)] + [
            (0, 0, rule._prepare_tax_line_vals()) for rule in rules
        ]

    def action_load_default_deductions(self):
        """Replace the deduction lines with the configured defaults."""
        for rec in self:
            if rec.state not in ('pending', 'scheduled', 'cfo_approved',
                                 'fm_approved', 'voucher_generated'):
                raise UserError(
                    "Deductions can no longer be changed on %s at this stage." % rec.name
                )
            if not rec._uses_default_deductions():
                raise UserError(
                    "%s is not a contract payment, so it has no tax rules to load. "
                    "Its deductions come from the source document." % rec.name
                )
            rules = self.env['nbet.tax.rule']._rules_for_category(rec.category)
            if not rules:
                raise UserError(
                    "No statutory deduction rules are configured for this contract "
                    "category. Set them up under Treasury > Configuration > Tax Rules."
                )
            rec._apply_default_deductions()

    def action_schedule(self):
        for rec in self:
            if not rec.scheduled_date:
                raise UserError("Please set a scheduled payment date.")
            if not rec.payment_method:
                raise UserError("Please select a payment method.")
        self.write({
            'state': 'scheduled',
            'treasury_officer_id': self.env.user.id,
        })

    def action_cfo_approve(self):
        for rec in self:
            if rec.state != 'scheduled':
                raise UserError("Only scheduled payments can be approved by the CFO.")
        self.write({
            'state': 'cfo_approved',
            'cfo_approved_by': self.env.user.id,
            'cfo_approval_date': fields.Datetime.now(),
        })

    def action_fm_approve(self):
        for rec in self:
            if rec.state != 'cfo_approved':
                raise UserError("Finance Manager approval requires prior CFO approval.")
            if rec.cfo_approved_by == self.env.user:
                raise UserError(
                    "Segregation of duties: the Finance Manager approval must be "
                    "performed by a different person than the CFO."
                )
        self.write({
            'state': 'fm_approved',
            'fm_approved_by': self.env.user.id,
            'fm_approval_date': fields.Datetime.now(),
        })

    # ------------------------------------------------------------------
    # Voucher generation
    # ------------------------------------------------------------------
    def _check_finance_officer(self):
        """Only the assigned finance officer (or a treasury manager) may raise vouchers."""
        self.ensure_one()
        if not self.finance_officer_id:
            raise UserError(
                "Assign a finance officer to %s before generating the payment vouchers."
                % self.name
            )
        if (self.finance_officer_id != self.env.user
                and not self.env.user.has_group('nbet_treasury.group_treasury_manager')):
            raise UserError(
                "Only the assigned finance officer (%s) or a Treasury Manager may "
                "generate the vouchers for %s."
                % (self.finance_officer_id.display_name, self.name)
            )

    def _source_approval_history(self):
        """Approvals the source document collected before it reached treasury.

        Overridden by the modules that feed treasury from somewhere other than a
        procurement payment request.
        """
        self.ensure_one()
        request = self.payment_request_id
        if not request:
            return []
        return [
            ('Payment Request Raised', request.requested_by, request.request_date),
            ('MD Review', request.md_reviewer_id, request.md_review_date),
            ('User Department Review', request.dept_reviewer_id, request.dept_review_date),
            ('MD Final Approval', request.md_final_approver_id, request.md_final_approval_date),
        ]

    def _voucher_approval_history(self):
        """Approval trail to stamp onto every voucher raised for this payment."""
        self.ensure_one()
        stages = self._source_approval_history() + [
            ('Treasury Scheduling', self.treasury_officer_id, self.create_date),
            ('CFO Approval', self.cfo_approved_by, self.cfo_approval_date),
            ('Finance Manager Approval', self.fm_approved_by, self.fm_approval_date),
        ]
        return [(stage, user, ts) for stage, user, ts in stages if user and ts]

    def _prepare_vendor_voucher_vals(self):
        self.ensure_one()
        return {
            'schedule_id': self.id,
            'voucher_type': 'vendor',
            'partner_id': self.vendor_id.id,
            'bank_account': self.bank_account,
            'description': self.description,
            'amount': self.net_amount,
            'payment_journal_id': self.payment_journal_id.id,
            'generated_by_id': self.env.user.id,
            'generated_on': fields.Datetime.now(),
        }

    def _prepare_tax_voucher_vals(self, tax_line):
        self.ensure_one()
        return {
            'schedule_id': self.id,
            'voucher_type': 'tax',
            'tax_line_id': tax_line.id,
            'partner_id': tax_line.tax_body_id.id,
            'description': '%s remittance for %s (%s)' % (
                tax_line.name, self.vendor_id.display_name, self.description or '',
            ),
            'amount': tax_line.amount,
            'payment_journal_id': self.payment_journal_id.id,
            'generated_by_id': self.env.user.id,
            'generated_on': fields.Datetime.now(),
        }

    def _check_voucher_generation(self):
        """Refuse to raise vouchers the payment cannot support.

        Source-specific; a payroll batch has no single vendor to pay, so it
        checks its payslips instead.
        """
        self.ensure_one()
        if not self.vendor_id:
            raise UserError("The payment request has no vendor set.")
        precision = self.currency_id.rounding or 0.01
        if float_compare(self.net_amount, 0.0, precision_rounding=precision) <= 0:
            raise UserError(
                "The net amount payable to the vendor on %s is not positive. "
                "Review the statutory deductions." % self.name
            )

    def _prepare_voucher_vals_list(self):
        """The vouchers to raise for this payment, one dict each.

        A contract payment pays the vendor and remits each deduction; other
        sources override this to split the payment their own way.
        """
        self.ensure_one()
        return (
            [self._prepare_vendor_voucher_vals()]
            + [self._prepare_tax_voucher_vals(line) for line in self.tax_line_ids]
        )

    def action_generate_vouchers(self):
        """Raise the vendor voucher plus a remittance voucher per statutory deduction."""
        Voucher = self.env['nbet.payment.voucher']
        for rec in self:
            if rec.state not in ('fm_approved', 'voucher_generated'):
                raise UserError(
                    "Vouchers can only be generated after Finance Manager approval."
                )
            rec._check_finance_officer()
            rec._check_voucher_generation()

            precision = rec.currency_id.rounding or 0.01
            for line in rec.tax_line_ids:
                if float_is_zero(line.amount, precision_rounding=precision):
                    raise UserError(
                        "Deduction '%s' on %s has a zero amount. Remove it or set an amount."
                        % (line.name, rec.name)
                    )

            # Regenerating replaces vouchers that have not yet gone to audit.
            stale = rec.voucher_ids.filtered(lambda v: v.state == 'draft')
            stale.unlink()
            if rec.voucher_ids.filtered(lambda v: v.state not in ('cancelled',)):
                raise UserError(
                    "%s already has vouchers submitted to audit. Reject the payment "
                    "first if they must be re-issued." % rec.name
                )

            if not rec.transaction_reference:
                rec.transaction_reference = self.env['ir.sequence'].next_by_code(
                    'nbet.payment.transaction'
                ) or rec.name

            history = rec._voucher_approval_history()
            vouchers = Voucher.create(rec._prepare_voucher_vals_list())
            for voucher in vouchers:
                for stage, user, timestamp in history:
                    voucher._log_approval(stage, user, timestamp)
                voucher._log_approval(
                    'Voucher Prepared', rec.finance_officer_id, fields.Datetime.now(),
                )
            for line in rec.tax_line_ids:
                line.voucher_id = vouchers.filtered(lambda v: v.tax_line_id == line)

            rec.state = 'voucher_generated'
            rec.message_post(
                body="%s payment voucher(s) generated by %s under transaction reference %s."
                     % (len(vouchers), self.env.user.display_name, rec.transaction_reference)
            )

    def action_forward_to_audit(self):
        for rec in self:
            if rec.state != 'voucher_generated':
                raise UserError("Generate the payment vouchers before forwarding to audit.")
            rec._check_finance_officer()
            if not rec.voucher_ids.filtered(lambda v: v.state == 'draft'):
                raise UserError("There are no draft vouchers to forward for %s." % rec.name)
            rec.voucher_ids.filtered(lambda v: v.state == 'draft').write({'state': 'submitted'})
            rec.state = 'audit_pending'
            rec.payment_request_id.audit_state = 'under_review'
            rec.message_post(
                body="%s and %s voucher(s) forwarded to Audit by %s."
                     % (rec._source_document_name(), len(rec.voucher_ids),
                        self.env.user.display_name)
            )

    # ------------------------------------------------------------------
    # Audit: one auditor reviews, a different auditor approves
    # ------------------------------------------------------------------
    def action_audit_review(self):
        for rec in self:
            if rec.state != 'audit_pending':
                raise UserError(
                    "Audit review requires the vouchers to be forwarded to audit first."
                )
            conflicts = []
            if self.env.user == rec.cfo_approved_by:
                conflicts.append("CFO")
            if self.env.user == rec.fm_approved_by:
                conflicts.append("Finance Manager")
            if self.env.user == rec.treasury_officer_id:
                conflicts.append("Treasury Officer")
            
            # For Finance Officer, check if they actually generated any vouchers
            if any(v.generated_by_id == self.env.user for v in rec.voucher_ids):
                conflicts.append("Finance Officer (Voucher Preparer)")
            
            if conflicts:
                raise UserError(
                    "Segregation of duties: the Audit Reviewer must be a different "
                    "person than the CFO, the Finance Manager, the Treasury Officer "
                    "and the Finance Officer who prepared the vouchers. "
                    "Current user is already assigned as: %s." % ", ".join(conflicts)
                )
            now = fields.Datetime.now()
            rec.write({
                'state': 'audit_reviewed',
                'audit_reviewer_id': self.env.user.id,
                'audit_review_date': now,
            })
            for voucher in rec.voucher_ids.filtered(lambda v: v.state == 'submitted'):
                voucher.state = 'reviewed'
                voucher._log_approval('Audit Review', self.env.user, now, rec.audit_review_notes)

    def action_audit_approve(self):
        for rec in self:
            if rec.state != 'audit_reviewed':
                raise UserError(
                    "Audit approval requires a prior review by another auditor."
                )
            if self.env.user == rec.audit_reviewer_id:
                raise UserError(
                    "Segregation of duties: the audit approval must be performed by a "
                    "different auditor than the one who reviewed (%s)."
                    % rec.audit_reviewer_id.display_name
                )
            conflicts = []
            if self.env.user == rec.cfo_approved_by:
                conflicts.append("CFO")
            if self.env.user == rec.fm_approved_by:
                conflicts.append("Finance Manager")
            if self.env.user == rec.treasury_officer_id:
                conflicts.append("Treasury Officer")
            
            # For Finance Officer, check if they actually generated any vouchers
            if any(v.generated_by_id == self.env.user for v in rec.voucher_ids):
                conflicts.append("Finance Officer (Voucher Preparer)")
            
            if conflicts:
                raise UserError(
                    "Segregation of duties: the Audit Approver must be a different "
                    "person than the CFO, the Finance Manager, the Treasury Officer "
                    "and the Finance Officer who prepared the vouchers. "
                    "Current user is already assigned as: %s." % ", ".join(conflicts)
                )
            now = fields.Datetime.now()
            rec.write({
                'state': 'audited',
                'auditor_id': self.env.user.id,
                'audit_date': now,
            })
            for voucher in rec.voucher_ids.filtered(lambda v: v.state == 'reviewed'):
                voucher.state = 'audited'
                voucher._log_approval('Audit Approval', self.env.user, now, rec.audit_notes)
            rec.payment_request_id.write({
                'audit_state': 'audited',
                'audit_reviewer_id': rec.audit_reviewer_id.id,
                'auditor_id': self.env.user.id,
                'audit_date': now,
            })
            rec.message_post(
                body="%s and its %s voucher(s) marked as audited "
                     "(reviewed by %s, approved by %s)."
                     % (rec._source_document_name(), len(rec.voucher_ids),
                        rec.audit_reviewer_id.display_name, self.env.user.display_name)
            )

    def action_view_vouchers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payment Vouchers',
            'res_model': 'nbet.payment.voucher',
            'view_mode': 'list,form',
            'domain': [('schedule_id', '=', self.id)],
            'context': {'default_schedule_id': self.id},
        }

    # ------------------------------------------------------------------
    # Payment settlement
    # ------------------------------------------------------------------
    def _post_withholding_entry(self, bill, date):
        """Move the amount withheld from the vendor onto the tax payable accounts.

        Debits the bill's payable account so the gross bill can be fully
        reconciled by the net payment, and credits each deduction's payable
        account, where the liability sits until it is remitted.
        """
        self.ensure_one()
        precision = self.currency_id.rounding or 0.01
        if not self.tax_line_ids or float_is_zero(self.tax_amount, precision_rounding=precision):
            return self.env['account.move']

        journal = self.env['account.journal'].sudo().search([
            ('type', '=', 'general'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            raise UserError(
                "No miscellaneous journal is configured, so the tax withheld on %s "
                "cannot be posted." % self.name
            )
        payable_account = bill.line_ids.sudo().filtered(
            lambda l: l.account_id.account_type == 'liability_payable'
        )[:1].account_id
        if not payable_account:
            return self.env['account.move']

        lines = [(0, 0, {
            'account_id': payable_account.id,
            'partner_id': self.vendor_id.id,
            'name': 'Tax withheld - %s' % self.name,
            'debit': self.tax_amount,
            'credit': 0.0,
        })]
        for tax in self.tax_line_ids:
            if not tax.tax_payable_account_id:
                raise UserError(
                    "Set a Tax Payable Account on the deduction '%s' of %s before "
                    "paying the vendor." % (tax.name, self.name)
                )
            lines.append((0, 0, {
                'account_id': tax.tax_payable_account_id.id,
                'partner_id': tax.tax_body_id.id,
                'name': '%s withheld - %s' % (tax.name, self.name),
                'debit': 0.0,
                'credit': tax.amount,
            }))
        move = self.env['account.move'].sudo().create({
            'journal_id': journal.id,
            'date': date or fields.Date.context_today(self),
            'ref': 'Tax withheld on %s (%s)' % (self.name, self.transaction_reference or ''),
            'line_ids': lines,
        })
        move.action_post()
        return move

    def _settle_if_fully_paid(self):
        """Close the payment out once every voucher raised for it has been paid."""
        self.ensure_one()
        vouchers = self.voucher_ids.filtered(lambda v: v.state != 'cancelled')
        if not vouchers or any(v.state != 'paid' for v in vouchers):
            return
        vendor_voucher = vouchers.filtered(lambda v: v.voucher_type == 'vendor')[:1]
        payment_date = vendor_voucher.payment_date or fields.Date.context_today(self)
        reference = self.payment_reference or vendor_voucher.payment_reference
        self.write({
            'state': 'paid',
            'payment_date': payment_date,
            'payment_reference': reference,
        })
        self._settle_source_document(payment_date, reference)
        self.message_post(
            body="All %s voucher(s) paid. Payment closed under reference %s."
                 % (len(vouchers), reference)
        )

    def _settle_source_document(self, payment_date, reference):
        """Close out whatever the treasury was paying for.

        Overridden by the modules that feed treasury from elsewhere, e.g. to mark
        the payslips of a paid payroll batch.
        """
        self.ensure_one()
        request = self.payment_request_id
        if not request:
            return
        request.write({'state': 'paid'})
        if request.milestone_id:
            request.milestone_id.write({'state': 'paid'})
        # A milestone contract only closes once every milestone has been paid;
        # until then it stays in execution so the rest can still be claimed.
        contract = request.contract_award_id
        contract_vals = {
            'payment_date': payment_date,
            'payment_reference': reference,
        }
        if contract.execution_mode != 'milestone' or contract._milestone_all_settled():
            contract_vals['state'] = 'completed'
        contract.write(contract_vals)

    def action_reject(self):
        """Send the payment back to the treasury officer, clearing approval stamps."""
        for rec in self:
            if rec.state not in ('cfo_approved', 'fm_approved', 'voucher_generated',
                                 'audit_pending', 'audit_reviewed'):
                raise UserError("Only payments in the approval chain can be rejected.")
            rec.voucher_ids.filtered(lambda v: v.state != 'cancelled').write({'state': 'cancelled'})
            rec.message_post(
                body="Payment rejected by %s and returned to the treasury officer for review."
                     % self.env.user.display_name
            )
        self.write({
            'state': 'scheduled',
            'cfo_approved_by': False,
            'cfo_approval_date': False,
            'fm_approved_by': False,
            'fm_approval_date': False,
            'audit_reviewer_id': False,
            'audit_review_date': False,
            'auditor_id': False,
            'audit_date': False,
        })
        self.mapped('payment_request_id').write({
            'audit_state': 'not_audited',
            'audit_reviewer_id': False,
            'auditor_id': False,
            'audit_date': False,
        })

    def action_hold(self):
        self.write({'state': 'on_hold'})

    def action_resume(self):
        self.write({
            'state': 'scheduled',
            'hold_reason': False,
        })

    def action_cancel(self):
        self.voucher_ids.filtered(lambda v: v.state != 'cancelled').write({'state': 'cancelled'})
        self.write({'state': 'cancelled'})
