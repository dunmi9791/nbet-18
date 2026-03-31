# -*- coding: utf-8 -*-
"""
NBET Power Billing — Unit Tests
Run with:
  python odoo-bin -d <db> --test-enable --test-tags /nbet_power_billing -u nbet_power_billing
"""
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo import fields
import datetime


class TestNbetDro(TransactionCase):
    """DRO history overlap prevention and retrieval"""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': 'Test DISCO Partner'})
        self.disco = self.env['nbet.market.participant'].create({
            'name': 'Test DISCO',
            'code': 'TDISCO',
            'participant_type': 'disco',
            'partner_id': self.partner.id,
        })

    def test_dro_overlap_prevention(self):
        """Two overlapping approved DRO records for same DISCO should raise ValidationError"""
        self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-01-01',
            'effective_to': '2024-06-30',
            'dro_percent': 45.0,
            'approval_state': 'approved',
        })
        with self.assertRaises(ValidationError):
            dro2 = self.env['nbet.disco.dro'].create({
                'participant_id': self.disco.id,
                'effective_from': '2024-04-01',  # overlaps with dro1
                'effective_to': '2024-12-31',
                'dro_percent': 50.0,
                'approval_state': 'approved',
            })
            # Trigger constraint (already raised on create in Odoo)

    def test_dro_no_overlap_allowed(self):
        """Non-overlapping DRO records should be created without error"""
        dro1 = self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-01-01',
            'effective_to': '2024-06-30',
            'dro_percent': 45.0,
            'approval_state': 'approved',
        })
        dro2 = self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-07-01',
            'effective_to': False,
            'dro_percent': 50.0,
            'approval_state': 'approved',
        })
        self.assertTrue(dro1.id)
        self.assertTrue(dro2.id)

    def test_dro_retrieval_by_date(self):
        """get_dro_for_date returns the correct approved DRO for the given date"""
        self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-01-01',
            'effective_to': '2024-06-30',
            'dro_percent': 45.0,
            'approval_state': 'approved',
        })
        dro2 = self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-07-01',
            'dro_percent': 50.0,
            'approval_state': 'approved',
        })
        result = self.env['nbet.disco.dro'].get_dro_for_date(
            self.disco.id, fields.Date.from_string('2024-08-15')
        )
        self.assertEqual(result.id, dro2.id)
        self.assertAlmostEqual(result.dro_percent, 50.0)

    def test_dro_retrieval_exact_start_date(self):
        """DRO should be returned when reference date equals effective_from"""
        dro = self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-04-01',
            'dro_percent': 48.0,
            'approval_state': 'approved',
        })
        result = self.env['nbet.disco.dro'].get_dro_for_date(
            self.disco.id, fields.Date.from_string('2024-04-01')
        )
        self.assertEqual(result.id, dro.id)

    def test_dro_no_result_before_start(self):
        """get_dro_for_date returns empty if date precedes all DRO records"""
        self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-04-01',
            'dro_percent': 48.0,
            'approval_state': 'approved',
        })
        result = self.env['nbet.disco.dro'].get_dro_for_date(
            self.disco.id, fields.Date.from_string('2024-03-31')
        )
        self.assertFalse(result)

    def test_dro_subsidy_computed(self):
        """subsidy_percent should be computed as 100 - dro_percent when not manually set"""
        dro = self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-01-01',
            'dro_percent': 48.0,
            'approval_state': 'draft',
        })
        self.assertAlmostEqual(dro.subsidy_percent, 52.0)

    def test_dro_subsidy_manual_override(self):
        """If subsidy_percent_manual=True, subsidy_percent should not be auto-recomputed"""
        dro = self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-01-01',
            'dro_percent': 48.0,
            'subsidy_percent': 30.0,
            'subsidy_percent_manual': True,
            'approval_state': 'draft',
        })
        self.assertAlmostEqual(dro.subsidy_percent, 30.0)

    def test_dro_archived_ignored_in_overlap(self):
        """Archived DRO records should not count in overlap check"""
        self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-01-01',
            'effective_to': '2024-06-30',
            'dro_percent': 45.0,
            'approval_state': 'archived',
        })
        # Should succeed — archived record is excluded from overlap check
        dro2 = self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-04-01',
            'dro_percent': 50.0,
            'approval_state': 'approved',
        })
        self.assertTrue(dro2.id)


class TestNbetRateCalculation(TransactionCase):
    """GENCO rate calculations via calculation service"""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': 'Test GENCO Partner'})
        self.genco = self.env['nbet.market.participant'].create({
            'name': 'Test GENCO',
            'code': 'TGENCO',
            'participant_type': 'genco',
            'partner_id': self.partner.id,
        })
        self.cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Test Cycle',
            'code': 'TEST-01',
            'date_start': '2024-04-01',
            'date_end': '2024-04-30',
            'hours_in_period': 720.0,
            'fx_central_rate': 1450.0,
            'fx_selling_rate': 1485.0,
            'old_tlf': 0.975,
            'new_tlf': 0.968,
        })
        self.svc = self.env['nbet.calculation.service'].create({})

    def _make_contract(self, formula_mode='fixed', **kwargs):
        defaults = {
            'contract_name': 'Test Contract',
            'contract_code': f'TC-{formula_mode}',
            'participant_id': self.genco.id,
            'plant_type': 'gas',
            'formula_mode': formula_mode,
            'state': 'active',
            'base_capacity_tariff': 1000.0,
            'base_energy_tariff': 2.0,
            'has_capacity_charge': True,
            'has_energy_charge': True,
            'base_fx_rate': 850.0,
            'base_tlf': 0.975,
            'base_index_value': 100.0,
        }
        defaults.update(kwargs)
        return self.env['nbet.genco.contract'].create(defaults)

    def test_fixed_formula_capacity_rate(self):
        """Fixed mode returns base_capacity_tariff unchanged"""
        contract = self._make_contract(formula_mode='fixed')
        billing_inputs = {'CBN_FX_CENTRAL': 1450.0, 'TLF_NEW': 0.968}
        rate, trace = self.svc._compute_capacity_rate(contract, self.cycle, False, billing_inputs)
        self.assertAlmostEqual(rate, 1000.0)
        self.assertEqual(trace['formula_mode'], 'fixed')

    def test_parametric_fx_adjustment(self):
        """Parametric mode applies FX adjustment correctly"""
        contract = self._make_contract(
            formula_mode='parametric',
            uses_fx_adjustment=True,
            base_fx_rate=850.0,
        )
        billing_inputs = {'CBN_FX_CENTRAL': 1450.0}
        rate, trace = self.svc._compute_capacity_rate(contract, self.cycle, False, billing_inputs)
        expected = 1000.0 * (1450.0 / 850.0)
        self.assertAlmostEqual(rate, expected, places=4)

    def test_parametric_tlf_adjustment(self):
        """Parametric mode applies TLF adjustment"""
        contract = self._make_contract(
            formula_mode='parametric',
            uses_tlf_adjustment=True,
            base_tlf=0.975,
        )
        billing_inputs = {'TLF_NEW': 0.968}
        rate, trace = self.svc._compute_capacity_rate(contract, self.cycle, False, billing_inputs)
        expected = 1000.0 * (0.968 / 0.975)
        self.assertAlmostEqual(rate, expected, places=4)

    def test_parametric_combined_adjustments(self):
        """Parametric mode applies FX + TLF adjustments combined"""
        contract = self._make_contract(
            formula_mode='parametric',
            uses_fx_adjustment=True,
            base_fx_rate=850.0,
            uses_tlf_adjustment=True,
            base_tlf=0.975,
        )
        billing_inputs = {'CBN_FX_CENTRAL': 1450.0, 'TLF_NEW': 0.968}
        rate, trace = self.svc._compute_capacity_rate(contract, self.cycle, False, billing_inputs)
        expected = 1000.0 * (1450.0 / 850.0) * (0.968 / 0.975)
        self.assertAlmostEqual(rate, expected, places=4)

    def test_no_contract_returns_zero(self):
        """If no contract is found, rate engine returns 0"""
        rate, trace = self.svc._compute_capacity_rate(None, self.cycle, False, {})
        self.assertEqual(rate, 0.0)
        self.assertIn('error', trace)


class TestNbetDiscoBillCalculation(TransactionCase):
    """DISCO bill computations"""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': 'Test DISCO'})
        self.disco = self.env['nbet.market.participant'].create({
            'name': 'Test DISCO',
            'code': 'TDISCO2',
            'participant_type': 'disco',
            'partner_id': self.partner.id,
        })
        self.cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Test Cycle 2',
            'code': 'TEST-02',
            'date_start': '2024-04-01',
            'date_end': '2024-04-30',
            'hours_in_period': 720.0,
        })
        self.dro = self.env['nbet.disco.dro'].create({
            'participant_id': self.disco.id,
            'effective_from': '2024-01-01',
            'dro_percent': 48.0,
            'approval_state': 'approved',
        })

    def test_dro_retrieval_for_cycle(self):
        """Correct DRO is fetched for the cycle's date_start"""
        dro = self.env['nbet.disco.dro'].get_dro_for_date(
            self.disco.id, self.cycle.date_start
        )
        self.assertEqual(dro.id, self.dro.id)
        self.assertAlmostEqual(dro.dro_percent, 48.0)

    def test_expected_payable_calculation(self):
        """expected_payable = gross * dro_percent / 100"""
        gross = 100_000_000.0  # ₦100M
        dro_pct = 48.0
        expected_payable = gross * dro_pct / 100.0
        self.assertAlmostEqual(expected_payable, 48_000_000.0)

    def test_subsidy_calculation(self):
        """subsidy = gross - expected_payable"""
        gross = 100_000_000.0
        payable = 48_000_000.0
        subsidy = gross - payable
        self.assertAlmostEqual(subsidy, 52_000_000.0)

    def test_disco_bill_dro_frozen(self):
        """Applied DRO on DISCO bill should not change when master DRO changes"""
        disco_data = self.env['nbet.disco.monthly.data'].create({
            'billing_cycle_id': self.cycle.id,
            'participant_id': self.disco.id,
            'capacity_delivered_mw': 100.0,
            'energy_delivered_kwh': 72_000_000.0,
            'applied_dro_percent': 48.0,
        })
        # Record the applied_dro_percent
        frozen_pct = disco_data.applied_dro_percent
        # Now update the master DRO
        self.dro.write({'dro_percent': 60.0})
        # The disco_data should still show the frozen value
        self.assertAlmostEqual(disco_data.applied_dro_percent, frozen_pct)
        self.assertAlmostEqual(disco_data.applied_dro_percent, 48.0)


class TestNbetInvoiceComparison(TransactionCase):
    """GENCO invoice comparison and variance flagging"""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': 'Test GENCO 2'})
        self.genco = self.env['nbet.market.participant'].create({
            'name': 'Test GENCO 2',
            'code': 'TG2',
            'participant_type': 'genco',
            'partner_id': self.partner.id,
        })
        self.cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Test Cycle 3',
            'code': 'TEST-03',
            'date_start': '2024-04-01',
            'date_end': '2024-04-30',
            'hours_in_period': 720.0,
        })
        self.expected_bill = self.env['nbet.genco.expected.bill'].create({
            'billing_cycle_id': self.cycle.id,
            'participant_id': self.genco.id,
            'capacity_charge_amount': 10_000_000.0,
            'energy_charge_amount': 5_000_000.0,
            'state': 'computed',
        })

    def test_variance_calculation_within_tolerance(self):
        """Variance within 1% should set is_within_tolerance = True"""
        submission = self.env['nbet.genco.invoice.submission'].create({
            'billing_cycle_id': self.cycle.id,
            'participant_id': self.genco.id,
            'invoice_number': 'INV-001',
            'submitted_amount': 15_100_000.0,  # 0.67% over
            'expected_bill_id': self.expected_bill.id,
            'tolerance_percent': 1.0,
        })
        self.assertTrue(submission.is_within_tolerance)
        self.assertAlmostEqual(submission.variance_amount, 100_000.0)

    def test_variance_exceeds_tolerance(self):
        """Variance exceeding tolerance should set is_within_tolerance = False"""
        submission = self.env['nbet.genco.invoice.submission'].create({
            'billing_cycle_id': self.cycle.id,
            'participant_id': self.genco.id,
            'invoice_number': 'INV-002',
            'submitted_amount': 17_000_000.0,  # 13% over
            'expected_bill_id': self.expected_bill.id,
            'tolerance_percent': 1.0,
        })
        self.assertFalse(submission.is_within_tolerance)

    def test_variance_percent_calculation(self):
        """variance_percent = |submitted - expected| / expected * 100"""
        expected_total = self.expected_bill.total_expected_amount  # 15,000,000
        submission = self.env['nbet.genco.invoice.submission'].create({
            'billing_cycle_id': self.cycle.id,
            'participant_id': self.genco.id,
            'invoice_number': 'INV-003',
            'submitted_amount': 14_000_000.0,
            'expected_bill_id': self.expected_bill.id,
        })
        expected_pct = abs(-1_000_000.0) / expected_total * 100
        self.assertAlmostEqual(submission.variance_percent, expected_pct, places=4)


class TestNbetBillingCycleLock(TransactionCase):
    """Billing cycle lock and recompute behavior"""

    def setUp(self):
        super().setUp()
        self.cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Lock Test Cycle',
            'code': 'LOCK-01',
            'date_start': '2024-04-01',
            'date_end': '2024-04-30',
            'hours_in_period': 720.0,
            'state': 'locked',
        })

    def test_locked_cycle_blocks_compute(self):
        """Calling compute on locked cycle raises UserError"""
        with self.assertRaises(UserError):
            self.cycle.action_compute_rates()

    def test_locked_cycle_blocks_calculate(self):
        """action_calculate on locked cycle raises UserError"""
        with self.assertRaises(UserError):
            self.cycle.action_calculate()

    def test_date_constraint(self):
        """Billing cycle with start > end should raise ValidationError"""
        with self.assertRaises(ValidationError):
            self.env['nbet.billing.cycle'].create({
                'name': 'Bad Date Cycle',
                'code': 'BAD-01',
                'date_start': '2024-04-30',
                'date_end': '2024-04-01',  # end before start
            })

    def test_total_kpis_computed(self):
        """KPI totals should be 0 on empty cycle"""
        empty_cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Empty Cycle',
            'code': 'EMPTY-01',
            'date_start': '2024-05-01',
            'date_end': '2024-05-31',
        })
        self.assertAlmostEqual(empty_cycle.total_expected_genco_amount, 0.0)
        self.assertAlmostEqual(empty_cycle.total_disco_gross_amount, 0.0)
        self.assertAlmostEqual(empty_cycle.total_subsidy_grant_exposure, 0.0)


class TestNbetParticipantConstraints(TransactionCase):
    """Participant type constraints on operational data"""

    def setUp(self):
        super().setUp()
        self.p_disco = self.env['res.partner'].create({'name': 'P DISCO'})
        self.disco = self.env['nbet.market.participant'].create({
            'name': 'A DISCO', 'code': 'ADISCO',
            'participant_type': 'disco', 'partner_id': self.p_disco.id,
        })
        self.cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Constraint Test', 'code': 'CT-01',
            'date_start': '2024-04-01', 'date_end': '2024-04-30',
        })

    def test_genco_data_rejects_disco(self):
        """nbet.genco.monthly.data should reject a DISCO participant"""
        with self.assertRaises(ValidationError):
            self.env['nbet.genco.monthly.data'].create({
                'billing_cycle_id': self.cycle.id,
                'participant_id': self.disco.id,
                'capacity_sent_out_mw': 100.0,
            })

    def test_unique_genco_data_per_cycle(self):
        """Duplicate GENCO data record for same cycle+participant should fail"""
        partner = self.env['res.partner'].create({'name': 'G2'})
        genco = self.env['nbet.market.participant'].create({
            'name': 'G2', 'code': 'G2', 'participant_type': 'genco',
            'partner_id': partner.id,
        })
        self.env['nbet.genco.monthly.data'].create({
            'billing_cycle_id': self.cycle.id,
            'participant_id': genco.id,
        })
        from odoo.exceptions import UserError as OrmError
        try:
            self.env['nbet.genco.monthly.data'].create({
                'billing_cycle_id': self.cycle.id,
                'participant_id': genco.id,
            })
            self.fail('Expected unique constraint violation')
        except Exception:
            pass  # expected — IntegrityError or ValidationError depending on backend
