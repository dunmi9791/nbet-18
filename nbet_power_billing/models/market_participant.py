# -*- coding: utf-8 -*-
"""
NBET Market Participant
Represents GENCOs, DISCOs, TSOs, traders, and other entities in the Nigerian
electricity market.  Each participant is linked to an Odoo res.partner so that
the full Odoo accounting and contact ecosystem is available.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class NbetMarketParticipant(models.Model):
    _name = 'nbet.market.participant'
    _description = 'NBET Market Participant'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'participant_type, name'

    # ── Identity ───────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Participant Name', required=True, tracking=True, index=True,
    )
    code = fields.Char(
        string='Code', required=True, tracking=True, index=True,
        help='Short unique identifier, e.g. EGBIN, IBEDC.',
    )
    participant_type = fields.Selection(
        selection=[
            ('genco', 'GENCO (Generation Company)'),
            ('disco', 'DISCO (Distribution Company)'),
            ('tso', 'TSO (Transmission System Operator)'),
            ('trader', 'Electricity Trader'),
            ('other', 'Other'),
        ],
        string='Type', required=True, tracking=True, index=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Odoo Contact', ondelete='restrict',
        help='Link to the Odoo partner record used for invoicing and payments.',
    )
    active = fields.Boolean(default=True, tracking=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )

    # ── Computed ───────────────────────────────────────────────────────────────
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'[{rec.code}] {rec.name}' if rec.code else rec.name

    # ── Smart-button counts ────────────────────────────────────────────────────
    contract_count = fields.Integer(compute='_compute_contract_count', string='Contracts')
    dro_count = fields.Integer(compute='_compute_dro_count', string='DRO Records')

    def _compute_contract_count(self):
        for rec in self:
            rec.contract_count = self.env['nbet.genco.contract'].search_count(
                [('participant_id', '=', rec.id)]
            )

    def _compute_dro_count(self):
        for rec in self:
            rec.dro_count = self.env['nbet.disco.dro'].search_count(
                [('participant_id', '=', rec.id)]
            )

    # ── Constraints ────────────────────────────────────────────────────────────
    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)',
         'Participant code must be unique per company.'),
    ]

    # ── Actions ────────────────────────────────────────────────────────────────
    def action_view_contracts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Contracts — {self.name}',
            'res_model': 'nbet.genco.contract',
            'view_mode': 'list,form',
            'domain': [('participant_id', '=', self.id)],
            'context': {'default_participant_id': self.id},
        }

    def action_view_dro(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'DRO History — {self.name}',
            'res_model': 'nbet.disco.dro',
            'view_mode': 'list,form',
            'domain': [('participant_id', '=', self.id)],
            'context': {'default_participant_id': self.id},
        }
