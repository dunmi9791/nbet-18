# -*- coding: utf-8 -*-
import base64
import csv
import io
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

# ── Template column definitions ─────────────────────────────────────────────

INPUTS_COLUMNS = [
    ('input_type_code', 'Input Type Code'),
    ('input_label', 'Input Label'),
    ('value', 'Value'),
    ('remarks', 'Remarks'),
]

GENCO_COLUMNS = [
    ('participant_code', 'Participant Code'),
    ('capacity_sent_out_mw', 'Capacity Sent Out (MW)'),
    ('gross_energy_kwh', 'Gross Energy (kWh)'),
    ('net_energy_kwh', 'Net Energy (kWh)'),
    ('capacity_import_mw', 'Import Capacity (MW)'),
    ('energy_import_kwh', 'Import Energy (kWh)'),
    ('net_energy_import_kwh', 'Net Import Energy (kWh)'),
    ('invoiced_capacity_mw', 'Invoiced Capacity (MW)'),
    ('invoiced_energy_kwh', 'Invoiced Energy (kWh)'),
    ('gas_fx_rate', 'Gas FX Rate (₦/$)'),
    ('remarks', 'Remarks'),
]

DISCO_COLUMNS = [
    ('participant_code', 'Participant Code'),
    ('capacity_delivered_mw', 'Capacity Delivered (MW)'),
    ('energy_delivered_kwh', 'Energy Delivered (kWh)'),
    ('market_allocation_basis', 'Allocation Basis'),
    ('remarks', 'Remarks'),
]

INPUTS_SAMPLE_ROWS = [
    ['CBN_FX_CENTRAL', 'CBN Central Rate', '460.50', ''],
    ['CBN_FX_SELLING', 'CBN Selling Rate', '461.00', ''],
    ['TLF_OLD', 'TLF Old', '0.0462', ''],
    ['TLF_NEW', 'TLF New', '0.0431', ''],
    ['HOURS_IN_MONTH', 'Hours in Month', '720', ''],
    ['AGIP_INDEX', 'AGIP Quarterly Index', '1.234', ''],
    ['AGIP_FX', 'AGIP Exchange Rate', '460.00', ''],
]

GENCO_SAMPLE_ROWS = [
    ['EGBIN', '440.00', '290000000', '280000000', '0', '0', '0', '0', '0', '0', ''],
    ['AFAM_VI', '320.00', '210000000', '200000000', '0', '0', '0', '0', '0', '0', ''],
]

DISCO_SAMPLE_ROWS = [
    ['IBEDC', '500.00', '340000000', 'ATC-based', ''],
    ['EKEDC', '600.00', '410000000', 'Metered', ''],
]


class NbetCsvUploadWizard(models.TransientModel):
    _name = 'nbet.csv.upload.wizard'
    _description = 'NBET CSV/Excel Upload Wizard'

    billing_cycle_id = fields.Many2one(
        'nbet.billing.cycle', string='Billing Cycle', required=True,
    )
    data_type = fields.Selection(
        selection=[
            ('inputs', 'Billing Cycle Inputs'),
            ('genco_data', 'GENCO Operational Data'),
            ('disco_data', 'DISCO Data'),
        ],
        string='Data Type', required=True, default='inputs',
    )
    upload_file = fields.Binary(string='Upload File', required=True, attachment=False)
    upload_filename = fields.Char(string='Filename')
    state = fields.Selection(
        selection=[('upload', 'Upload'), ('preview', 'Preview'), ('done', 'Done')],
        default='upload',
    )
    batch_id = fields.Many2one('nbet.import.batch', string='Import Batch', readonly=True)
    preview_html = fields.Html(string='Preview', readonly=True)
    row_count = fields.Integer(string='Rows Parsed', readonly=True)
    error_count = fields.Integer(string='Errors', readonly=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Template Download
    # ─────────────────────────────────────────────────────────────────────────

    def action_download_template(self):
        self.ensure_one()
        columns, sample_rows = self._get_template_spec()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([col[1] for col in columns])
        for row in sample_rows:
            writer.writerow(row)
        csv_bytes = output.getvalue().encode('utf-8-sig')
        filename = f'nbet_{self.data_type}_template.csv'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(csv_bytes),
            'mimetype': 'text/csv',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def _get_template_spec(self):
        specs = {
            'inputs': (INPUTS_COLUMNS, INPUTS_SAMPLE_ROWS),
            'genco_data': (GENCO_COLUMNS, GENCO_SAMPLE_ROWS),
            'disco_data': (DISCO_COLUMNS, DISCO_SAMPLE_ROWS),
        }
        return specs[self.data_type]

    # ─────────────────────────────────────────────────────────────────────────
    # Preview
    # ─────────────────────────────────────────────────────────────────────────

    def action_preview(self):
        self.ensure_one()
        if not self.upload_file:
            raise UserError('Please upload a file.')

        rows = self._parse_file()
        if not rows:
            raise UserError('The uploaded file contains no data rows.')

        columns, _ = self._get_template_spec()
        expected_headers = [col[0] for col in columns]
        header_labels = [col[1] for col in columns]

        file_headers = rows[0]
        col_map = self._map_columns(file_headers, columns)
        if not col_map:
            raise UserError(
                'Could not match file columns to the expected template.\n\n'
                f'Expected columns: {", ".join(header_labels)}\n'
                f'Found: {", ".join(str(h) for h in file_headers)}'
            )

        batch = self.env['nbet.import.batch'].create({
            'name': f'CSV Import: {self.billing_cycle_id.name} — {self.data_type} — {self.upload_filename or "file"}',
            'billing_cycle_id': self.billing_cycle_id.id,
            'source_filename': self.upload_filename or '',
            'state': 'draft',
        })

        data_rows = rows[1:]
        errors = 0
        for row_idx, row in enumerate(data_rows, start=2):
            try:
                self._stage_row(batch, row, row_idx, col_map)
            except Exception as e:
                errors += 1
                self.env['nbet.import.error.log'].create({
                    'batch_id': batch.id,
                    'sheet_name': 'CSV',
                    'row_number': row_idx,
                    'error_type': 'parse_error',
                    'message': str(e)[:500],
                })

        batch.state = 'previewed'
        self.write({
            'batch_id': batch.id,
            'state': 'preview',
            'row_count': len(data_rows),
            'error_count': errors,
            'preview_html': self._build_preview_html(batch),
        })
        return self._reopen()

    # ─────────────────────────────────────────────────────────────────────────
    # Confirm Import
    # ─────────────────────────────────────────────────────────────────────────

    def action_confirm_import(self):
        self.ensure_one()
        if not self.batch_id:
            raise UserError('No import batch found. Please run Preview first.')

        batch = self.batch_id
        cycle = self.billing_cycle_id
        imported = 0
        errors = 0

        for line in batch.line_ids.filtered(lambda l: l.status == 'mapped'):
            try:
                handler = {
                    'cycle_input': self._commit_input_line,
                    'genco_data': self._commit_genco_line,
                    'disco_data': self._commit_disco_line,
                }
                handler[line.record_type](line, cycle)
                line.status = 'imported'
                imported += 1
            except Exception as e:
                line.status = 'error'
                line.error_message = str(e)[:250]
                errors += 1

        batch.state = 'confirmed'
        self.state = 'done'
        cycle.message_post(
            body=(
                f'CSV/Excel import completed ({self.data_type}): '
                f'{imported} records imported, {errors} errors. '
                f'Batch: {batch.name}'
            )
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.import.batch',
            'res_id': batch.id,
            'view_mode': 'form',
        }

    # ─────────────────────────────────────────────────────────────────────────
    # File Parsing
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_file(self):
        raw = base64.b64decode(self.upload_file)
        fname = (self.upload_filename or '').lower()

        if fname.endswith(('.xlsx', '.xls')):
            return self._parse_excel(raw)
        return self._parse_csv(raw)

    def _parse_csv(self, raw):
        for encoding in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
            try:
                text = raw.decode(encoding)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            raise UserError('Could not decode the CSV file. Please save it as UTF-8.')

        reader = csv.reader(io.StringIO(text))
        return [row for row in reader if any(cell.strip() for cell in row)]

    def _parse_excel(self, raw):
        if not HAS_OPENPYXL:
            raise UserError(
                'The openpyxl Python package is required for Excel import.\n'
                'Install it with: pip install openpyxl'
            )
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheet = wb.active
        rows = []
        for row in sheet.iter_rows(values_only=True):
            str_row = [str(cell) if cell is not None else '' for cell in row]
            if any(cell.strip() for cell in str_row):
                rows.append(str_row)
        return rows

    # ─────────────────────────────────────────────────────────────────────────
    # Column Mapping
    # ─────────────────────────────────────────────────────────────────────────

    def _map_columns(self, file_headers, template_columns):
        normalized_headers = [str(h).lower().strip() for h in file_headers]
        col_map = {}
        for field_key, label in template_columns:
            for idx, header in enumerate(normalized_headers):
                if header == field_key.lower() or header == label.lower():
                    col_map[field_key] = idx
                    break
        required_keys = {col[0] for col in template_columns if col[0] != 'remarks'}
        if self.data_type == 'inputs':
            required_keys = {'input_type_code', 'value'}
        elif self.data_type == 'genco_data':
            required_keys = {'participant_code'}
        elif self.data_type == 'disco_data':
            required_keys = {'participant_code'}

        if not required_keys.issubset(col_map.keys()):
            return None
        return col_map

    def _get_cell(self, row, col_map, key, default=''):
        idx = col_map.get(key)
        if idx is None or idx >= len(row):
            return default
        return str(row[idx]).strip() if row[idx] else default

    # ─────────────────────────────────────────────────────────────────────────
    # Staging Rows
    # ─────────────────────────────────────────────────────────────────────────

    def _stage_row(self, batch, row, row_idx, col_map):
        if self.data_type == 'inputs':
            self._stage_input_row(batch, row, row_idx, col_map)
        elif self.data_type == 'genco_data':
            self._stage_genco_row(batch, row, row_idx, col_map)
        elif self.data_type == 'disco_data':
            self._stage_disco_row(batch, row, row_idx, col_map)

    def _stage_input_row(self, batch, row, row_idx, col_map):
        code = self._get_cell(row, col_map, 'input_type_code')
        if not code:
            return
        value = self._get_cell(row, col_map, 'value')
        label = self._get_cell(row, col_map, 'input_label', code)
        self.env['nbet.import.batch.line'].create({
            'batch_id': batch.id,
            'sheet_name': 'CSV',
            'row_number': row_idx,
            'record_type': 'cycle_input',
            'field_label': label,
            'raw_value': value,
            'parsed_value_float': self._safe_float(value),
            'input_type_code': code,
            'status': 'mapped',
        })

    def _stage_genco_row(self, batch, row, row_idx, col_map):
        participant = self._get_cell(row, col_map, 'participant_code')
        if not participant:
            return
        genco_fields = [
            'capacity_sent_out_mw', 'gross_energy_kwh', 'net_energy_kwh',
            'capacity_import_mw', 'energy_import_kwh', 'net_energy_import_kwh',
            'invoiced_capacity_mw', 'invoiced_energy_kwh', 'gas_fx_rate',
        ]
        for field_name in genco_fields:
            raw = self._get_cell(row, col_map, field_name)
            if not raw:
                continue
            self.env['nbet.import.batch.line'].create({
                'batch_id': batch.id,
                'sheet_name': 'CSV',
                'row_number': row_idx,
                'record_type': 'genco_data',
                'field_label': field_name,
                'raw_value': raw,
                'parsed_value_float': self._safe_float(raw),
                'participant_code': participant,
                'status': 'mapped',
            })

    def _stage_disco_row(self, batch, row, row_idx, col_map):
        participant = self._get_cell(row, col_map, 'participant_code')
        if not participant:
            return
        disco_float_fields = ['capacity_delivered_mw', 'energy_delivered_kwh']
        disco_char_fields = ['market_allocation_basis']

        for field_name in disco_float_fields:
            raw = self._get_cell(row, col_map, field_name)
            if not raw:
                continue
            self.env['nbet.import.batch.line'].create({
                'batch_id': batch.id,
                'sheet_name': 'CSV',
                'row_number': row_idx,
                'record_type': 'disco_data',
                'field_label': field_name,
                'raw_value': raw,
                'parsed_value_float': self._safe_float(raw),
                'participant_code': participant,
                'status': 'mapped',
            })

        for field_name in disco_char_fields:
            raw = self._get_cell(row, col_map, field_name)
            if not raw:
                continue
            self.env['nbet.import.batch.line'].create({
                'batch_id': batch.id,
                'sheet_name': 'CSV',
                'row_number': row_idx,
                'record_type': 'disco_data',
                'field_label': field_name,
                'raw_value': raw,
                'parsed_value_char': raw,
                'participant_code': participant,
                'status': 'mapped',
            })

    # ─────────────────────────────────────────────────────────────────────────
    # Commit to real models
    # ─────────────────────────────────────────────────────────────────────────

    def _commit_input_line(self, line, cycle):
        input_type = self.env['nbet.billing.input.type'].search(
            [('code', '=', line.input_type_code)], limit=1,
        )
        if not input_type:
            raise ValueError(f'Unknown input type code: {line.input_type_code}')
        existing = self.env['nbet.billing.cycle.input'].search([
            ('billing_cycle_id', '=', cycle.id),
            ('input_type_id', '=', input_type.id),
        ], limit=1)
        vals = {
            'billing_cycle_id': cycle.id,
            'input_type_id': input_type.id,
            'value_float': line.parsed_value_float,
            'source_sheet': 'CSV Import',
            'source_cell': f'Row {line.row_number}',
        }
        if existing:
            existing.write(vals)
        else:
            self.env['nbet.billing.cycle.input'].create(vals)

    def _commit_genco_line(self, line, cycle):
        participant = self._match_participant(line.participant_code)
        if not participant:
            raise ValueError(f'Could not match participant: {line.participant_code}')
        existing = self.env['nbet.genco.monthly.data'].search([
            ('billing_cycle_id', '=', cycle.id),
            ('participant_id', '=', participant.id),
        ], limit=1)
        if not existing:
            existing = self.env['nbet.genco.monthly.data'].create({
                'billing_cycle_id': cycle.id,
                'participant_id': participant.id,
                'imported_from_file': True,
                'source_sheet': 'CSV Import',
                'source_row_no': line.row_number,
            })
        if hasattr(existing, line.field_label):
            existing.write({line.field_label: line.parsed_value_float})

    def _commit_disco_line(self, line, cycle):
        participant = self._match_participant(line.participant_code)
        if not participant:
            raise ValueError(f'Could not match participant: {line.participant_code}')
        existing = self.env['nbet.disco.monthly.data'].search([
            ('billing_cycle_id', '=', cycle.id),
            ('participant_id', '=', participant.id),
        ], limit=1)
        if not existing:
            existing = self.env['nbet.disco.monthly.data'].create({
                'billing_cycle_id': cycle.id,
                'participant_id': participant.id,
            })
        if line.parsed_value_char and hasattr(existing, line.field_label):
            existing.write({line.field_label: line.parsed_value_char})
        elif hasattr(existing, line.field_label):
            existing.write({line.field_label: line.parsed_value_float})

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _match_participant(self, name_or_code):
        if not name_or_code:
            return None
        p = self.env['nbet.market.participant'].search(
            [('code', '=ilike', name_or_code.strip())], limit=1,
        )
        if p:
            return p
        p = self.env['nbet.market.participant'].search(
            [('name', 'ilike', name_or_code.strip())], limit=1,
        )
        return p or None

    def _safe_float(self, value):
        if not value:
            return 0.0
        s = str(value).strip().replace(',', '').replace('%', '')
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    def _build_preview_html(self, batch):
        lines = batch.line_ids[:100]
        rows_html = ''
        for line in lines:
            badge_cls = 'success' if line.status == 'mapped' else 'warning'
            rows_html += (
                f'<tr>'
                f'<td>{line.row_number}</td>'
                f'<td>{line.record_type}</td>'
                f'<td>{line.participant_code or ""}</td>'
                f'<td>{line.field_label or ""}</td>'
                f'<td>{line.raw_value or ""}</td>'
                f'<td>{line.parsed_value_float:.4f}</td>'
                f'<td><span class="badge bg-{badge_cls}">{line.status}</span></td>'
                f'</tr>'
            )
        error_count = batch.error_count
        error_note = (
            f'<p class="text-danger"><strong>{error_count} error(s)</strong> during parsing.</p>'
            if error_count else ''
        )
        return (
            f'{error_note}'
            f'<p>Showing first {len(lines)} of {batch.total_lines} staged rows.</p>'
            f'<table class="table table-sm table-bordered">'
            f'<thead><tr>'
            f'<th>Row</th><th>Type</th><th>Participant</th>'
            f'<th>Field</th><th>Raw Value</th><th>Parsed Value</th><th>Status</th>'
            f'</tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            f'</table>'
        )

    def action_reset(self):
        self.ensure_one()
        if self.batch_id and self.batch_id.state in ('draft', 'previewed'):
            self.batch_id.action_cancel()
        self.write({
            'state': 'upload',
            'batch_id': False,
            'upload_file': False,
            'upload_filename': False,
            'preview_html': False,
            'row_count': 0,
            'error_count': 0,
        })
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nbet.csv.upload.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
