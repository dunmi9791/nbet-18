# -*- coding: utf-8 -*-
"""
NBET Import Batch
Staging models for Excel import batches.
"""
from odoo import models, fields, api


class NbetImportBatch(models.Model):
    _name = 'nbet.import.batch'
    _description = 'NBET Excel Import Batch'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(string='Batch Name', required=True)
    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle', required=True, ondelete='restrict',
    )
    source_filename = fields.Char(string='Source Filename')
    import_date = fields.Datetime(string='Import Date', default=fields.Datetime.now)
    imported_by = fields.Many2one('res.users', default=lambda self: self.env.user)
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('previewed', 'Previewed'),
            ('confirmed', 'Confirmed'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft', required=True, tracking=True,
    )
    line_ids = fields.One2many('nbet.import.batch.line', 'batch_id', string='Lines')
    error_log_ids = fields.One2many('nbet.import.error.log', 'batch_id', string='Errors')
    notes = fields.Text(string='Notes')
    total_lines = fields.Integer(compute='_compute_counts')
    error_count = fields.Integer(compute='_compute_counts')

    def _compute_counts(self):
        for rec in self:
            rec.total_lines = len(rec.line_ids)
            rec.error_count = len(rec.error_log_ids)

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset(self):
        self.write({'state': 'draft'})

    def action_view_lines(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Staged Lines',
            'res_model': 'nbet.import.batch.line',
            'view_mode': 'list',
            'domain': [('batch_id', '=', self.id)],
            'context': {'default_batch_id': self.id},
        }

    def action_view_errors(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import Errors',
            'res_model': 'nbet.import.error.log',
            'view_mode': 'list',
            'domain': [('batch_id', '=', self.id)],
            'context': {'default_batch_id': self.id},
        }


class NbetImportBatchLine(models.Model):
    _name = 'nbet.import.batch.line'
    _description = 'NBET Import Batch Line'
    _order = 'batch_id, sheet_name, row_number'

    batch_id = fields.Many2one('nbet.import.batch', required=True, ondelete='cascade', index=True)
    sheet_name = fields.Char(string='Sheet')
    row_number = fields.Integer(string='Row')
    record_type = fields.Selection(
        selection=[
            ('cycle_input', 'Cycle Input'),
            ('genco_data', 'GENCO Operational Data'),
            ('rate_data', 'Rate Data'),
            ('other', 'Other'),
        ],
        string='Record Type',
    )
    field_label = fields.Char(string='Field Label')
    raw_value = fields.Char(string='Raw Value')
    parsed_value_float = fields.Float(string='Parsed Float', digits=(16, 6))
    parsed_value_char = fields.Char(string='Parsed Text')
    participant_code = fields.Char(string='Participant Code')
    input_type_code = fields.Char(string='Input Type Code')
    status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('mapped', 'Mapped'),
            ('imported', 'Imported'),
            ('error', 'Error'),
            ('skipped', 'Skipped'),
        ],
        default='pending',
    )
    error_message = fields.Char(string='Error')
    target_record_ref = fields.Char(string='Target Record')


class NbetImportErrorLog(models.Model):
    _name = 'nbet.import.error.log'
    _description = 'NBET Import Error Log'
    _order = 'batch_id, sheet_name, row_number'

    batch_id = fields.Many2one('nbet.import.batch', required=True, ondelete='cascade', index=True)
    sheet_name = fields.Char(string='Sheet')
    row_number = fields.Integer(string='Row')
    cell_ref = fields.Char(string='Cell')
    error_type = fields.Selection(
        selection=[
            ('parse_error', 'Parse Error'),
            ('mapping_error', 'Mapping Error'),
            ('validation_error', 'Validation Error'),
            ('duplicate', 'Duplicate'),
            ('other', 'Other'),
        ],
        string='Error Type',
    )
    message = fields.Text(string='Message')
    raw_value = fields.Char(string='Raw Value')
