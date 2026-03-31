# -*- coding: utf-8 -*-
"""
NBET Rate Snapshot
Stores the exact rates used for a GENCO in a billing cycle with full formula
trace.  Versioned: when rates are recomputed, a new version is created and the
previous one is flagged is_current=False.  This preserves the full audit trail.
"""
from odoo import models, fields, api
import json


class NbetRateSnapshot(models.Model):
    _name = 'nbet.rate.snapshot'
    _description = 'NBET Rate Snapshot'
    _order = 'billing_cycle_id desc, participant_id, version desc'

    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle',
        required=True, ondelete='cascade', index=True,
    )
    participant_id = fields.Many2one(
        'nbet.market.participant', string='GENCO',
        required=True, ondelete='restrict',
    )
    contract_id = fields.Many2one(
        'nbet.genco.contract', string='Contract',
    )

    # ── Rates ─────────────────────────────────────────────────────────────────
    capacity_rate = fields.Float(
        string='Capacity Rate (₦/MW/h)', digits=(16, 6),
        help='Final capacity rate applied for billing calculation.',
    )
    energy_rate = fields.Float(
        string='Energy Rate (₦/kWh)', digits=(16, 8),
        help='Final energy rate applied for billing calculation.',
    )

    # ── Inputs Used ───────────────────────────────────────────────────────────
    fx_rate_used = fields.Float(string='FX Rate Used (₦/$)', digits=(16, 4))
    index_value_used = fields.Float(string='Index Value Used', digits=(16, 6))
    tlf_used = fields.Float(string='TLF Used', digits=(10, 6))

    # ── Trace ─────────────────────────────────────────────────────────────────
    formula_trace_json = fields.Text(
        string='Formula Trace (JSON)',
        help='JSON dump of the full calculation trace dict produced by the rate engine.',
    )
    notes = fields.Text(string='Notes')

    # ── Version Tracking ──────────────────────────────────────────────────────
    compute_date = fields.Datetime(
        string='Computed On', default=fields.Datetime.now,
    )
    computed_by = fields.Many2one(
        'res.users', string='Computed By',
        default=lambda self: self.env.user,
    )
    version = fields.Integer(string='Version', default=1)
    is_current = fields.Boolean(
        string='Current Version', default=True, index=True,
        help='Only the most recent snapshot is marked as current.',
    )
    currency_id = fields.Many2one(
        'res.currency', related='billing_cycle_id.currency_id',
    )

    # ── Helpers ────────────────────────────────────────────────────────────────
    def get_trace_dict(self):
        """Parse formula_trace_json and return as dict."""
        self.ensure_one()
        if self.formula_trace_json:
            try:
                return json.loads(self.formula_trace_json)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def set_trace(self, trace_dict):
        """Serialize trace_dict to formula_trace_json."""
        self.ensure_one()
        try:
            self.formula_trace_json = json.dumps(trace_dict, indent=2, default=str)
        except (TypeError, ValueError):
            self.formula_trace_json = str(trace_dict)

    @api.model
    def create_or_update(self, billing_cycle_id, participant_id, values):
        """Create a new rate snapshot, bumping version and un-setting is_current
        on any previous snapshots for the same cycle + participant.

        Args:
            billing_cycle_id (int): billing cycle ID
            participant_id (int): market participant ID
            values (dict): fields to set on the new snapshot

        Returns:
            New nbet.rate.snapshot record
        """
        # Un-flag previous versions
        old = self.search([
            ('billing_cycle_id', '=', billing_cycle_id),
            ('participant_id', '=', participant_id),
            ('is_current', '=', True),
        ])
        max_version = max(old.mapped('version'), default=0)
        old.write({'is_current': False})

        values.update({
            'billing_cycle_id': billing_cycle_id,
            'participant_id': participant_id,
            'is_current': True,
            'version': max_version + 1,
            'compute_date': fields.Datetime.now(),
        })
        return self.create(values)
