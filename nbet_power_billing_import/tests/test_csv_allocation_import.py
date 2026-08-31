# -*- coding: utf-8 -*-
"""
Tests for CSV import of DISCO → GENCO rate allocation lines.
"""
import base64

from odoo.tests.common import TransactionCase


class TestCsvAllocationImport(TransactionCase):

    def setUp(self):
        super().setUp()
        Participant = self.env['nbet.market.participant']
        self.disco = Participant.create({
            'name': 'Import DISCO', 'code': 'IMPDISCO',
            'participant_type': 'disco',
            'partner_id': self.env['res.partner'].create({'name': 'Import DISCO'}).id,
        })
        self.genco_a = Participant.create({
            'name': 'Import Genco A', 'code': 'IMPGA',
            'participant_type': 'genco',
            'partner_id': self.env['res.partner'].create({'name': 'Import Genco A'}).id,
        })
        self.genco_b = Participant.create({
            'name': 'Import Genco B', 'code': 'IMPGB',
            'participant_type': 'genco',
            'partner_id': self.env['res.partner'].create({'name': 'Import Genco B'}).id,
        })
        self.cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Import Cycle', 'code': 'IMP-01',
            'date_start': '2024-04-01', 'date_end': '2024-04-30',
        })

    def _run_import(self, csv_text):
        wizard = self.env['nbet.csv.upload.wizard'].create({
            'billing_cycle_id': self.cycle.id,
            'data_type': 'disco_allocations',
            'upload_file': base64.b64encode(csv_text.encode('utf-8')),
            'upload_filename': 'allocations.csv',
        })
        wizard.action_preview()
        wizard.action_confirm_import()
        return wizard

    def _allocations(self):
        return self.env['nbet.disco.genco.allocation'].search([
            ('billing_cycle_id', '=', self.cycle.id),
            ('disco_id', '=', self.disco.id),
        ])

    def test_allocation_import_creates_lines(self):
        """Importing allocation rows creates allocation lines (and the DISCO
        monthly data record if it doesn't exist yet)."""
        self._run_import(
            'DISCO Code,GENCO Code,Allocation (%),Remarks\n'
            'IMPDISCO,IMPGA,60,\n'
            'IMPDISCO,IMPGB,25,\n'
        )
        allocs = self._allocations()
        self.assertEqual(len(allocs), 2)
        by_genco = {a.genco_id: a.allocation_percent for a in allocs}
        self.assertAlmostEqual(by_genco[self.genco_a], 60.0)
        self.assertAlmostEqual(by_genco[self.genco_b], 25.0)
        disco_data = allocs[0].disco_data_id
        self.assertEqual(disco_data.participant_id, self.disco)
        self.assertAlmostEqual(disco_data.total_allocation_percent, 85.0)

    def test_allocation_reimport_replaces(self):
        """A second import replaces the DISCO's existing allocation lines
        instead of merging with them."""
        self._run_import(
            'DISCO Code,GENCO Code,Allocation (%),Remarks\n'
            'IMPDISCO,IMPGA,60,\n'
            'IMPDISCO,IMPGB,25,\n'
        )
        self._run_import(
            'DISCO Code,GENCO Code,Allocation (%),Remarks\n'
            'IMPDISCO,IMPGA,100,\n'
        )
        allocs = self._allocations()
        self.assertEqual(len(allocs), 1)
        self.assertEqual(allocs.genco_id, self.genco_a)
        self.assertAlmostEqual(allocs.allocation_percent, 100.0)

    def test_allocation_import_rejects_non_genco(self):
        """A row whose GENCO column names a DISCO is flagged as an error line
        and no allocation is created for it."""
        wizard = self._run_import(
            'DISCO Code,GENCO Code,Allocation (%),Remarks\n'
            'IMPDISCO,IMPDISCO,50,\n'
        )
        self.assertFalse(self._allocations())
        error_lines = wizard.batch_id.line_ids.filtered(lambda l: l.status == 'error')
        self.assertEqual(len(error_lines), 1)

    def test_allocation_import_unknown_disco_errors(self):
        """A row naming an unknown DISCO code becomes an error line."""
        wizard = self._run_import(
            'DISCO Code,GENCO Code,Allocation (%),Remarks\n'
            'NOSUCH,IMPGA,50,\n'
        )
        error_lines = wizard.batch_id.line_ids.filtered(lambda l: l.status == 'error')
        self.assertEqual(len(error_lines), 1)
