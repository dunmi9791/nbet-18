# -*- coding: utf-8 -*-
"""
DISCO customer invoice creation from an approved DISCO bill.
"""
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install')
class TestDiscoInvoice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.revenue_account = cls.env['account.account'].create({
            'name': 'NBET Test Energy Revenue',
            'code': 'NBT4001',
            'account_type': 'income',
        })
        cls.capacity_account = cls.env['account.account'].create({
            'name': 'NBET Test Capacity Revenue',
            'code': 'NBT4002',
            'account_type': 'income',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Test DISCO Partner'})
        cls.disco = cls.env['nbet.market.participant'].create({
            'name': 'Test DISCO',
            'code': 'TDISCO',
            'participant_type': 'disco',
            'partner_id': cls.partner.id,
        })
        cls.cycle = cls.env['nbet.billing.cycle'].create({
            'name': 'Test Cycle',
            'code': 'TC-INV',
            'date_start': '2026-01-01',
            'date_end': '2026-01-31',
        })

    def _make_bill(self):
        return self.env['nbet.disco.bill'].create({
            'billing_cycle_id': self.cycle.id,
            'participant_id': self.disco.id,
            'applied_dro_percent': 50.0,
            'state': 'approved',
            'line_ids': [
                (0, 0, {'line_type': 'capacity', 'description': 'Capacity', 'amount': 1000.0}),
                (0, 0, {'line_type': 'energy', 'description': 'Energy', 'amount': 3000.0}),
            ],
        })

    def _set_param(self, key, value):
        self.env['ir.config_parameter'].sudo().set_param(f'nbet_power_billing.{key}', value)

    def test_invoice_uses_accounts_saved_in_settings(self):
        """Accounts stored only as Settings parameters are still used for invoicing."""
        self._set_param('revenue_energy_account_id', self.revenue_account.id)
        self._set_param('revenue_capacity_account_id', self.capacity_account.id)
        bill = self._make_bill()
        bill.action_create_invoice()
        self.assertEqual(bill.state, 'invoiced')
        self.assertEqual(
            set(bill.invoice_move_id.invoice_line_ids.account_id.ids),
            {self.revenue_account.id, self.capacity_account.id},
        )
        cfg = self.env['nbet.billing.config'].get_config(self.company)
        self.assertEqual(cfg.revenue_energy_account_id, self.revenue_account)

    def test_missing_accounts_named_in_error(self):
        """Without revenue accounts the error says which line types lack one."""
        bill = self._make_bill()
        with self.assertRaisesRegex(ValidationError, 'Capacity Charge, Energy Charge'):
            bill.action_create_invoice()

    def test_missing_partner_error(self):
        self.disco.partner_id = False
        bill = self._make_bill()
        with self.assertRaisesRegex(ValidationError, 'no linked Odoo Contact'):
            bill.action_create_invoice()

    def test_config_menu_opens_existing_record(self):
        cfg = self.env['nbet.billing.config'].get_config(self.company)
        action = self.env['nbet.billing.config'].action_open_config()
        self.assertEqual(action['res_id'], cfg.id)
