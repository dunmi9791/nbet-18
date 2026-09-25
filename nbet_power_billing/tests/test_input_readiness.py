# -*- coding: utf-8 -*-
"""
NBET Power Billing — Billing cycle input readiness
Run with:
  python odoo-bin -d <db> --test-enable --test-tags /nbet_power_billing -u nbet_power_billing
"""
from odoo.tests.common import TransactionCase


class TestNbetInputReadiness(TransactionCase):
    """Missing contract inputs are flagged per participating GENCO and block calculation"""

    def setUp(self):
        super().setUp()
        self.cycle = self.env['nbet.billing.cycle'].create({
            'name': 'Readiness Cycle',
            'code': 'READY-01',
            'date_start': '2024-04-01',
            'date_end': '2024-04-30',
            'hours_in_period': 720.0,
        })
        self.cap_type = self.env.ref('nbet_power_billing.component_type_capacity')
        self.eng_type = self.env.ref('nbet_power_billing.component_type_energy')
        self.cpi_type = self.env['nbet.billing.input.type'].create({
            'name': 'US CPI (test)',
            'code': 'TEST_US_CPI',
            'category': 'index',
        })
        self.fx_type = self.env['nbet.billing.input.type'].search(
            [('code', '=', 'CBN_FX_CENTRAL')], limit=1)
        self.hydro = self._make_genco('Test Hydro', 'THYDRO')
        self.hydro_contract = self._make_myto_contract(self.hydro, 'RC-HYDRO')
        self._add_monthly_data(self.hydro)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _make_genco(self, name, code):
        partner = self.env['res.partner'].create({'name': name})
        return self.env['nbet.market.participant'].create({
            'name': name,
            'code': code,
            'participant_type': 'genco',
            'partner_id': partner.id,
        })

    def _make_myto_contract(self, genco, code):
        contract = self.env['nbet.genco.contract'].create({
            'contract_name': f'{code} contract',
            'contract_code': code,
            'participant_id': genco.id,
            'plant_type': 'hydro',
            'formula_mode': 'myto_components',
            'state': 'active',
            'rate_param_ids': [
                (0, 0, {'code': 'fx', 'name': 'FX', 'base_value': 197.0,
                        'billing_input_code': 'CBN_FX_CENTRAL'}),
                (0, 0, {'code': 'cpi', 'name': 'US CPI', 'base_value': 108.47,
                        'billing_input_code': 'TEST_US_CPI'}),
                # Constant: no input code, always uses its base value
                (0, 0, {'code': 'k', 'name': 'Constant', 'base_value': 2.0}),
                # Has an input code but no formula reads current_unused
                (0, 0, {'code': 'unused', 'name': 'Unused', 'base_value': 1.0,
                        'billing_input_code': 'TEST_UNUSED'}),
            ],
            'line_ids': [
                (0, 0, {'sequence': 10, 'name': 'Fixed O&M', 'component_code': 'fixed_om',
                        'component_type_id': self.cap_type.id, 'basis': 'formula',
                        'base_value': 100.0,
                        'formula_expression': 'base_value * (current_fx / base_fx) '
                                              '* (current_cpi / base_cpi) * current_k / base_k'}),
                (0, 0, {'sequence': 20, 'name': 'Energy', 'component_code': 'energy_charge',
                        'component_type_id': self.eng_type.id, 'basis': 'formula',
                        'base_value': 1.0,
                        'formula_expression': 'max(base_value, fixed_om / 100)'}),
            ],
        })
        return contract

    def _add_monthly_data(self, genco, capacity=100.0, energy=50000.0):
        return self.env['nbet.genco.monthly.data'].create({
            'billing_cycle_id': self.cycle.id,
            'participant_id': genco.id,
            'invoiced_capacity_mw': capacity,
            'invoiced_energy_kwh': energy,
        })

    def _set_input(self, input_type, value):
        self.env['nbet.billing.cycle.input'].create({
            'billing_cycle_id': self.cycle.id,
            'input_type_id': input_type.id,
            'value_float': value,
        })

    def _issues(self, **filters):
        self.cycle.action_check_inputs()
        lines = self.cycle.readiness_ids
        for field, value in filters.items():
            lines = lines.filtered(lambda l: l[field] == value)
        return lines

    # ── Requirement resolution ─────────────────────────────────────────────────
    def test_myto_requirements_only_referenced_params(self):
        """MYTO needs inputs only for params with an input code that a formula reads"""
        required, issues = self.hydro_contract._get_input_requirements()
        self.assertEqual(set(required), {'CBN_FX_CENTRAL', 'TEST_US_CPI'})
        self.assertFalse(issues)

    def test_unknown_formula_name_is_setup_gap(self):
        """A formula reading an undefined name is a blocking set-up gap"""
        self.hydro_contract.line_ids[0].formula_expression = 'base_value * current_cpii / base_cpi'
        gaps = self._issues(issue_type='setup_gap')
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps.severity, 'blocking')
        self.assertIn('current_cpii', gaps.description)

    def test_later_component_reference_is_setup_gap(self):
        """A formula may only use component codes computed by earlier lines"""
        self.hydro_contract.line_ids[0].formula_expression = 'energy_charge * 2'
        self.assertTrue(self._issues(issue_type='setup_gap'))

    def test_parametric_requirements(self):
        """Parametric flags map to their fixed input codes; zero base is a gap"""
        genco = self._make_genco('Test Gas', 'TGAS')
        contract = self.env['nbet.genco.contract'].create({
            'contract_name': 'Gas', 'contract_code': 'RC-GAS',
            'participant_id': genco.id, 'plant_type': 'gas',
            'formula_mode': 'parametric', 'state': 'active',
            'uses_fx_adjustment': True, 'base_fx_rate': 850.0,
            'uses_index_adjustment': True, 'base_index_value': 0.0,
        })
        required, issues = contract._get_input_requirements()
        self.assertEqual(set(required), {'CBN_FX_CENTRAL'})
        self.assertEqual(len(issues), 1)

    # ── Cycle check ────────────────────────────────────────────────────────────
    def test_missing_inputs_are_blocking(self):
        """Inputs the contract needs but the cycle lacks are blocking"""
        missing = self._issues(issue_type='missing_input')
        self.assertEqual(set(missing.mapped('input_code')), {'CBN_FX_CENTRAL', 'TEST_US_CPI'})
        self.assertTrue(all(l.severity == 'blocking' for l in missing))
        self.assertEqual(missing.participant_id, self.hydro)
        self.assertEqual(self.cycle.readiness_blocking_count, 2)
        self.assertIn('TEST_US_CPI', self.cycle.readiness_summary)

    def test_cycle_level_fallback_field_counts_as_entered(self):
        """fx_central_rate on the cycle satisfies CBN_FX_CENTRAL"""
        self.cycle.fx_central_rate = 1450.0
        missing = self._issues(issue_type='missing_input')
        self.assertEqual(missing.mapped('input_code'), ['TEST_US_CPI'])

    def test_zero_input_is_warning(self):
        """An input entered as 0 is a warning, not a blocker"""
        self._set_input(self.fx_type, 1450.0)
        self._set_input(self.cpi_type, 0.0)
        self.cycle.action_check_inputs()
        zero = self.cycle.readiness_ids.filtered(lambda l: l.issue_type == 'zero_input')
        self.assertEqual(zero.input_code, 'TEST_US_CPI')
        self.assertEqual(zero.severity, 'warning')
        self.assertEqual(self.cycle.readiness_blocking_count, 0)

    def test_zero_monthly_quantity_is_warning(self):
        """Zero invoiced quantity for a charged component is a warning"""
        self.cycle.genco_data_ids.invoiced_energy_kwh = 0.0
        lines = self._issues(issue_type='missing_monthly_data')
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.severity, 'warning')

    def test_non_participating_genco_not_checked(self):
        """A GENCO with a contract but no monthly data in the cycle is ignored"""
        other = self._make_genco('Idle GENCO', 'TIDLE')
        self._make_myto_contract(other, 'RC-IDLE')
        self.cycle.action_check_inputs()
        self.assertNotIn(other, self.cycle.readiness_ids.participant_id)

    def test_input_gap_grouped_across_gencos(self):
        """One missing input shared by two GENCOs is summarised once with both names"""
        second = self._make_genco('Second Hydro', 'THYDRO2')
        self._make_myto_contract(second, 'RC-HYDRO2')
        self._add_monthly_data(second)
        self._set_input(self.fx_type, 1450.0)
        self.cycle.action_check_inputs()
        self.assertEqual(self.cycle.readiness_summary.count('TEST_US_CPI'), 1)
        self.assertIn('Second Hydro', self.cycle.readiness_summary)
        self.assertIn('Test Hydro', self.cycle.readiness_summary)

    def test_participant_without_contract_is_blocking(self):
        genco = self._make_genco('No Contract', 'TNOCON')
        self._add_monthly_data(genco)
        lines = self._issues(issue_type='no_contract')
        self.assertEqual(lines.participant_id, genco)
        self.assertEqual(lines.severity, 'blocking')

    # ── Enforcement ────────────────────────────────────────────────────────────
    def test_calculate_blocked_until_inputs_entered(self):
        """Calculation returns a danger notification and computes nothing while blocked"""
        action = self.cycle.action_calculate()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'danger')
        self.assertIn('TEST_US_CPI', action['params']['message'])
        self.assertFalse(self.cycle.rate_snapshot_ids)

        self._set_input(self.fx_type, 1450.0)
        self._set_input(self.cpi_type, 120.0)
        self.assertFalse(self.cycle.action_calculate())
        snapshot = self.cycle.rate_snapshot_ids.filtered('is_current')
        self.assertEqual(len(snapshot), 1)
        self.assertFalse(snapshot.has_input_gaps)

    def test_review_blocked_when_input_removed_after_calculation(self):
        self._set_input(self.fx_type, 1450.0)
        self._set_input(self.cpi_type, 120.0)
        self.cycle.state = 'input_loaded'
        self.cycle.action_calculate()
        self.assertEqual(self.cycle.state, 'calculated')
        self.cycle.input_line_ids.filtered(lambda l: l.input_type_id == self.cpi_type).unlink()
        self.env.user.groups_id |= self.env.ref('nbet_power_billing.group_nbet_billing_reviewer')
        action = self.cycle.action_review()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(self.cycle.state, 'calculated')

    def test_engine_records_fallback_on_snapshot(self):
        """Direct engine calls with a missing input flag the snapshot"""
        svc = self.env['nbet.calculation.service'].create({})
        snapshot = svc._compute_rate_snapshot(self.cycle, self.hydro, {'CBN_FX_CENTRAL': 1450.0})
        self.assertTrue(snapshot.has_input_gaps)
        self.assertIn('TEST_US_CPI', snapshot.input_gap_notes)
