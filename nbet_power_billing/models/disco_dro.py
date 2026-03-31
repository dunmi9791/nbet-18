# -*- coding: utf-8 -*-
"""
NBET DISCO DRO History
DRO = Dispatch Reliability Obligation / Distribution Remittance Obligation.
It represents the percentage of their gross bill that a DISCO is expected to pay.
The remainder is covered by government subsidy or grant.

CRITICAL DESIGN NOTES:
- Full date-range history is retained; records are NEVER deleted.
- No two active records for the same DISCO may have overlapping date ranges.
- The subsidy_percent is computed as (100 - dro_percent) unless manually overridden.
- When a DISCO bill is computed, the system freezes the applied_dro_percent on
  the bill so that future DRO changes do NOT alter posted invoices.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class NbetDiscoDro(models.Model):
    _name = 'nbet.disco.dro'
    _description = 'NBET DISCO DRO History'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'participant_id, effective_from desc'

    # ── Core Fields ────────────────────────────────────────────────────────────
    participant_id = fields.Many2one(
        'nbet.market.participant', string='DISCO', required=True,
        domain=[('participant_type', '=', 'disco')], ondelete='restrict',
        tracking=True, index=True,
    )
    effective_from = fields.Date(
        string='Effective From', required=True, tracking=True,
    )
    effective_to = fields.Date(
        string='Effective To', tracking=True,
        help='Leave blank for open-ended (current) DRO.',
    )
    dro_percent = fields.Float(
        string='DRO (%)', required=True, digits=(5, 2), tracking=True,
        help='Percentage of gross bill the DISCO is obligated to pay. Range 0–100.',
    )
    subsidy_percent = fields.Float(
        string='Subsidy/Grant (%)', digits=(5, 2), tracking=True,
        compute='_compute_subsidy_percent', store=True, readonly=False,
        help='Percentage to be covered by subsidy/grant. Defaults to 100 - DRO%.',
    )
    subsidy_percent_manual = fields.Boolean(
        string='Subsidy % Manually Set', default=False,
        help='If True, subsidy_percent will not be auto-recomputed from dro_percent.',
    )

    # ── Source / Approval ──────────────────────────────────────────────────────
    source_reference = fields.Char(
        string='Source Reference',
        help='NERC order number, board minute, or other authorising document reference.',
    )
    approval_state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('archived', 'Archived'),
        ],
        string='Approval State', default='draft', required=True, tracking=True,
    )
    approved_by = fields.Many2one(
        'res.users', string='Approved By', tracking=True,
    )
    approved_date = fields.Datetime(string='Approved On', tracking=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
    )

    # ── Computed ───────────────────────────────────────────────────────────────
    @api.depends('dro_percent', 'subsidy_percent_manual')
    def _compute_subsidy_percent(self):
        for rec in self:
            if not rec.subsidy_percent_manual:
                rec.subsidy_percent = 100.0 - rec.dro_percent

    @api.onchange('subsidy_percent')
    def _onchange_subsidy_percent(self):
        """Mark as manually set if user edits subsidy_percent directly."""
        self.subsidy_percent_manual = True

    # ── Overlap Constraint ────────────────────────────────────────────────────
    @api.constrains('participant_id', 'effective_from', 'effective_to', 'approval_state')
    def _check_no_overlap(self):
        """Prevent two active DRO records for the same DISCO from having
        overlapping effective date ranges."""
        FAR_FUTURE = fields.Date.from_string('2099-12-31')
        for rec in self:
            if rec.approval_state == 'archived':
                continue  # archived records are excluded from overlap check
            domain = [
                ('participant_id', '=', rec.participant_id.id),
                ('id', '!=', rec.id),
                ('approval_state', '!=', 'archived'),
            ]
            others = self.search(domain)
            rec_to = rec.effective_to or FAR_FUTURE
            for other in others:
                other_to = other.effective_to or FAR_FUTURE
                # Overlap condition: rec starts before other ends AND rec ends after other starts
                if rec.effective_from <= other_to and rec_to >= other.effective_from:
                    raise ValidationError(
                        f'DRO record for {rec.participant_id.name} overlaps with '
                        f'an existing record '
                        f'({other.effective_from} – {other.effective_to or "open"}).\n'
                        f'Please set effective_to on the earlier record before '
                        f'creating a new one, or archive the conflicting record.'
                    )

    @api.constrains('dro_percent', 'subsidy_percent')
    def _check_percent_range(self):
        for rec in self:
            if not (0.0 <= rec.dro_percent <= 100.0):
                raise ValidationError(
                    f'DRO % must be between 0 and 100 (got {rec.dro_percent}).'
                )
            if not (0.0 <= rec.subsidy_percent <= 100.0):
                raise ValidationError(
                    f'Subsidy % must be between 0 and 100 (got {rec.subsidy_percent}).'
                )

    # ── State Transitions ──────────────────────────────────────────────────────
    def action_approve(self):
        for rec in self:
            rec.write({
                'approval_state': 'approved',
                'approved_by': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            })

    def action_archive_dro(self):
        self.write({'approval_state': 'archived'})

    def action_reset_to_draft(self):
        self.write({'approval_state': 'draft'})

    # ── Class-level Helper ────────────────────────────────────────────────────
    @api.model
    def get_dro_for_date(self, participant_id, reference_date):
        """Return the approved DRO record for a DISCO that is effective on
        reference_date.

        Args:
            participant_id (int): ID of the nbet.market.participant (DISCO).
            reference_date (date): The date to look up, typically billing_cycle.date_start.

        Returns:
            nbet.disco.dro recordset (single record) or empty recordset.

        Raises:
            UserError: if more than one active record matches (data integrity issue).
        """
        domain = [
            ('participant_id', '=', participant_id),
            ('approval_state', '=', 'approved'),
            ('effective_from', '<=', reference_date),
            '|',
            ('effective_to', '>=', reference_date),
            ('effective_to', '=', False),
        ]
        records = self.search(domain)
        if len(records) > 1:
            raise UserError(
                f'Multiple approved DRO records found for participant ID {participant_id} '
                f'on {reference_date}. Please resolve the overlap in DRO History.'
            )
        return records
