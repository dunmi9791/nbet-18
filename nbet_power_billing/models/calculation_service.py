# -*- coding: utf-8 -*-
"""
NBET Billing Calculation Service
Central engine for all rate and bill calculations.

Design principles:
- All logic lives here, not buried in button methods.
- Each formula mode (fixed, parametric, python_expression, structured_components)
  has its own code path.
- Every result carries a trace_dict so the audit trail is complete.
- The service is a TransientModel so it can be instantiated per-request
  without polluting the database.

MAPPING NOTE: The parametric adjustment formulas below were derived from the
legacy NBET Excel workbook ("Rates" sheet).  Verify the following with the
NBET Settlement Team:
  1. Whether FX adjustment uses CBN Central or Selling rate.
  2. Whether TLF applied is old_tlf or new_tlf (or which contract uses which).
  3. The Agip gas index quarterly update schedule and which GENCOs it applies to.
  4. Whether energy charge uses the same TLF as capacity charge.
"""
import json
import logging
import time
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class NbetCalculationService(models.TransientModel):
    _name = 'nbet.calculation.service'
    _description = 'NBET Billing Calculation Service'

    # ──────────────────────────────────────────────────────────────────────────
    # Public Entry Points
    # ──────────────────────────────────────────────────────────────────────────

    def run_for_cycle(self, cycle_id):
        """Full calculation: rates + GENCO bills + DISCO bills."""
        cycle = self.env['nbet.billing.cycle'].browse(cycle_id)
        self.compute_rates_for_cycle(cycle_id)
        self.compute_genco_bills_for_cycle(cycle_id)
        self.compute_disco_bills_for_cycle(cycle_id)
        if cycle.state in ('draft', 'input_loaded'):
            cycle.state = 'calculated'
        return True

    def compute_rates_for_cycle(self, cycle_id):
        """Compute and store rate snapshots for all GENCOs with data in the cycle."""
        t0 = time.time()
        cycle = self.env['nbet.billing.cycle'].browse(cycle_id)
        billing_inputs = self._get_billing_inputs(cycle)
        genco_data_recs = cycle.genco_data_ids
        count = 0
        errors = []
        for gd in genco_data_recs:
            try:
                self._compute_rate_snapshot(cycle, gd.participant_id, billing_inputs)
                count += 1
            except Exception as e:
                _logger.exception('Rate computation failed for %s', gd.participant_id.name)
                errors.append(f'{gd.participant_id.name}: {e}')
        self._log_run(cycle, 'rate_compute', count, 0, errors, time.time() - t0)

    def compute_genco_bills_for_cycle(self, cycle_id):
        """Compute expected bills for all GENCOs with rate snapshots."""
        t0 = time.time()
        cycle = self.env['nbet.billing.cycle'].browse(cycle_id)
        billing_inputs = self._get_billing_inputs(cycle)
        count = 0
        errors = []
        for gd in cycle.genco_data_ids:
            try:
                self._compute_genco_expected_bill(cycle, gd.participant_id, billing_inputs, gd)
                count += 1
            except Exception as e:
                _logger.exception('GENCO bill computation failed for %s', gd.participant_id.name)
                errors.append(f'{gd.participant_id.name}: {e}')
        self._log_run(cycle, 'genco_bill_compute', count, 0, errors, time.time() - t0)

    def compute_disco_bills_for_cycle(self, cycle_id):
        """Compute DISCO bills for all DISCOs with data in the cycle."""
        t0 = time.time()
        cycle = self.env['nbet.billing.cycle'].browse(cycle_id)
        billing_inputs = self._get_billing_inputs(cycle)
        count = 0
        errors = []
        for dd in cycle.disco_data_ids:
            try:
                self._compute_disco_bill(cycle, dd.participant_id, billing_inputs, dd)
                count += 1
            except Exception as e:
                _logger.exception('DISCO bill computation failed for %s', dd.participant_id.name)
                errors.append(f'{dd.participant_id.name}: {e}')
        self._log_run(cycle, 'disco_bill_compute', 0, count, errors, time.time() - t0)

    # ──────────────────────────────────────────────────────────────────────────
    # Billing Input Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_billing_inputs(self, cycle):
        """Return dict of input_type.code -> float value for the billing cycle.

        The cycle's own TLF/FX fields serve as fallback if no cycle.input_line entry exists.

        Returns:
            dict: e.g. {'CBN_FX_CENTRAL': 1550.0, 'TLF_OLD': 0.975, 'TLF_NEW': 0.968, ...}
        """
        result = {}
        for inp in cycle.input_line_ids:
            if inp.input_type_id and inp.input_type_id.code:
                result[inp.input_type_id.code] = inp.get_float_value()

        # Merge cycle-level shorthand fields as fallbacks
        fallbacks = {
            'TLF_OLD': cycle.old_tlf,
            'TLF_NEW': cycle.new_tlf,
            'CBN_FX_CENTRAL': cycle.fx_central_rate,
            'CBN_FX_SELLING': cycle.fx_selling_rate,
            'HOURS_IN_MONTH': cycle.hours_in_period,
        }
        for k, v in fallbacks.items():
            if k not in result and v:
                result[k] = v

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Contract & DRO Resolution
    # ──────────────────────────────────────────────────────────────────────────

    def _get_active_contract(self, participant, cycle):
        """Find the active nbet.genco.contract for a participant valid on cycle date_start."""
        domain = [
            ('participant_id', '=', participant.id),
            ('state', '=', 'active'),
            '|', ('start_date', '=', False),
            ('start_date', '<=', cycle.date_start),
            '|', ('end_date', '=', False),
            ('end_date', '>=', cycle.date_start),
        ]
        return self.env['nbet.genco.contract'].search(domain, limit=1)

    def _compute_dro_allocation(self, participant, billing_date):
        """Fetch approved DRO for DISCO on billing_date."""
        dro = self.env['nbet.disco.dro'].get_dro_for_date(
            participant.id, billing_date,
        )
        if not dro:
            raise UserError(
                f'No approved DRO record found for {participant.name} '
                f'effective on {billing_date}. Please create and approve a DRO record.'
            )
        return dro

    # ──────────────────────────────────────────────────────────────────────────
    # Rate Computation
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_rate_snapshot(self, cycle, participant, billing_inputs):
        """Compute and store the rate snapshot for one GENCO."""
        contract = self._get_active_contract(participant, cycle)
        monthly_data = cycle.genco_data_ids.filtered(
            lambda d: d.participant_id == participant
        )[:1]

        cap_rate, cap_trace = self._compute_capacity_rate(
            contract, cycle, monthly_data, billing_inputs
        )
        eng_rate, eng_trace = self._compute_energy_rate(
            contract, cycle, monthly_data, billing_inputs
        )

        # Determine which TLF and FX were used
        fx_used = billing_inputs.get('CBN_FX_CENTRAL', contract.base_fx_rate if contract else 0.0)
        # MAPPING NOTE: Determine per-contract whether old_tlf or new_tlf applies.
        # Current rule: use new_tlf if contract.uses_tlf_adjustment else base_tlf.
        # Verify with NBET team which TLF applies to which plant types.
        if contract and contract.uses_tlf_adjustment:
            tlf_used = billing_inputs.get('TLF_NEW', contract.base_tlf)
        elif contract:
            tlf_used = contract.base_tlf
        else:
            tlf_used = billing_inputs.get('TLF_NEW', 1.0)

        index_used = billing_inputs.get('AGIP_INDEX', contract.base_index_value if contract else 1.0)

        trace = {
            'capacity': cap_trace,
            'energy': eng_trace,
            'fx_used': fx_used,
            'tlf_used': tlf_used,
            'index_used': index_used,
        }

        snapshot = self.env['nbet.rate.snapshot'].create_or_update(
            cycle.id, participant.id,
            {
                'contract_id': contract.id if contract else False,
                'capacity_rate': cap_rate,
                'energy_rate': eng_rate,
                'fx_rate_used': fx_used,
                'index_value_used': index_used,
                'tlf_used': tlf_used,
                'formula_trace_json': json.dumps(trace, indent=2, default=str),
            }
        )
        return snapshot

    def _compute_capacity_rate(self, contract, cycle, monthly_data, billing_inputs):
        """Compute the capacity rate for a GENCO.

        Returns:
            tuple: (rate: float, trace: dict)
        """
        if not contract:
            return 0.0, {'error': 'No active contract found'}

        mode = contract.formula_mode
        trace = {
            'formula_mode': mode,
            'base_capacity_tariff': contract.base_capacity_tariff,
            'contract_code': contract.contract_code,
            'plant_type': contract.plant_type,
        }

        if mode == 'fixed':
            rate = contract.base_capacity_tariff
            trace['result'] = rate
            trace['note'] = 'Fixed mode: base tariff returned unchanged.'

        elif mode == 'parametric':
            rate, trace = self._parametric_capacity_rate(contract, billing_inputs, trace)

        elif mode == 'python_expression':
            rate, trace = self._eval_capacity_rate(contract, cycle, monthly_data, billing_inputs, trace)

        elif mode == 'structured_components':
            rate, trace = self._component_capacity_rate(contract, billing_inputs, trace)

        else:
            rate = contract.base_capacity_tariff
            trace['note'] = f'Unknown formula mode "{mode}"; falling back to base tariff.'

        return rate, trace

    def _parametric_capacity_rate(self, contract, billing_inputs, trace):
        """Apply parametric FX / TLF / index adjustments to base capacity tariff."""
        rate = contract.base_capacity_tariff
        steps = []

        if contract.uses_fx_adjustment and contract.base_fx_rate:
            # MAPPING NOTE: verify whether CBN_FX_CENTRAL or CBN_FX_SELLING applies here
            fx_rate = billing_inputs.get('CBN_FX_CENTRAL', contract.base_fx_rate)
            adj = fx_rate / contract.base_fx_rate
            steps.append({
                'step': 'FX adjustment',
                'base_fx': contract.base_fx_rate,
                'current_fx': fx_rate,
                'ratio': adj,
                'rate_before': rate,
            })
            rate *= adj
            steps[-1]['rate_after'] = rate

        if contract.uses_tlf_adjustment and contract.base_tlf:
            # MAPPING NOTE: old_tlf vs new_tlf depends on contract — confirm with NBET team
            tlf = billing_inputs.get('TLF_NEW', contract.base_tlf)
            adj = tlf / contract.base_tlf
            steps.append({
                'step': 'TLF adjustment',
                'base_tlf': contract.base_tlf,
                'current_tlf': tlf,
                'ratio': adj,
                'rate_before': rate,
            })
            rate *= adj
            steps[-1]['rate_after'] = rate

        if contract.uses_index_adjustment and contract.base_index_value:
            # MAPPING NOTE: Agip index only for gas GENCOs — verify applicability
            index = billing_inputs.get('AGIP_INDEX', contract.base_index_value)
            adj = index / contract.base_index_value
            steps.append({
                'step': 'Index adjustment',
                'base_index': contract.base_index_value,
                'current_index': index,
                'ratio': adj,
                'rate_before': rate,
            })
            rate *= adj
            steps[-1]['rate_after'] = rate

        trace['parametric_steps'] = steps
        trace['result'] = rate
        return rate, trace

    def _eval_capacity_rate(self, contract, cycle, monthly_data, billing_inputs, trace):
        """Evaluate python_expression formula for capacity rate."""
        ctx = self._build_eval_context(contract, cycle, monthly_data, billing_inputs)
        # Find the capacity component line with a formula
        formula_line = contract.line_ids.filtered(
            lambda l: l.component_type == 'capacity' and l.basis == 'formula' and l.active
        )[:1]
        expression = formula_line.formula_expression if formula_line else None
        if not expression:
            # Fall back to base rate
            trace['note'] = 'No capacity formula expression found; using base tariff.'
            return contract.base_capacity_tariff, trace
        try:
            rate = float(safe_eval(expression, locals_dict=ctx))
            trace['expression'] = expression
            trace['context'] = {k: v for k, v in ctx.items() if isinstance(v, (int, float, str))}
            trace['result'] = rate
        except Exception as e:
            _logger.warning('Capacity formula eval failed: %s', e)
            rate = contract.base_capacity_tariff
            trace['eval_error'] = str(e)
            trace['fallback'] = 'base_capacity_tariff'
            trace['result'] = rate
        return rate, trace

    def _component_capacity_rate(self, contract, billing_inputs, trace):
        """Sum capacity tariff component lines."""
        rate = 0.0
        components = []
        for line in contract.line_ids.filtered(
            lambda l: l.component_type == 'capacity' and l.active
        ):
            val = self._resolve_component_value(line, billing_inputs)
            components.append({'name': line.name, 'value': val, 'basis': line.basis})
            rate += val
        trace['components'] = components
        trace['result'] = rate
        return rate, trace

    def _compute_energy_rate(self, contract, cycle, monthly_data, billing_inputs):
        """Compute the energy rate for a GENCO.  Same pattern as capacity rate."""
        if not contract:
            return 0.0, {'error': 'No active contract found'}

        mode = contract.formula_mode
        trace = {
            'formula_mode': mode,
            'base_energy_tariff': contract.base_energy_tariff,
            'contract_code': contract.contract_code,
        }

        if mode == 'fixed':
            rate = contract.base_energy_tariff
            trace['result'] = rate
            trace['note'] = 'Fixed mode: base tariff returned unchanged.'

        elif mode == 'parametric':
            # Energy rate typically only applies FX for gas plants
            rate = contract.base_energy_tariff
            steps = []
            if contract.uses_fx_adjustment and contract.base_fx_rate:
                fx_rate = billing_inputs.get('CBN_FX_CENTRAL', contract.base_fx_rate)
                adj = fx_rate / contract.base_fx_rate
                rate *= adj
                steps.append({'step': 'FX adjustment', 'ratio': adj, 'result': rate})
            # MAPPING NOTE: Confirm whether TLF applies to energy rate for all plant types
            trace['parametric_steps'] = steps
            trace['result'] = rate

        elif mode == 'python_expression':
            ctx = self._build_eval_context(contract, cycle, monthly_data, billing_inputs)
            formula_line = contract.line_ids.filtered(
                lambda l: l.component_type == 'energy' and l.basis == 'formula' and l.active
            )[:1]
            expression = formula_line.formula_expression if formula_line else None
            if expression:
                try:
                    rate = float(safe_eval(expression, locals_dict=ctx))
                except Exception as e:
                    rate = contract.base_energy_tariff
                    trace['eval_error'] = str(e)
            else:
                rate = contract.base_energy_tariff
            trace['result'] = rate

        elif mode == 'structured_components':
            rate = 0.0
            components = []
            for line in contract.line_ids.filtered(
                lambda l: l.component_type == 'energy' and l.active
            ):
                val = self._resolve_component_value(line, billing_inputs)
                components.append({'name': line.name, 'value': val})
                rate += val
            trace['components'] = components
            trace['result'] = rate

        else:
            rate = contract.base_energy_tariff
            trace['note'] = f'Unknown formula mode "{mode}"; using base energy tariff.'

        return rate, trace

    # ──────────────────────────────────────────────────────────────────────────
    # GENCO Expected Bill
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_genco_expected_bill(self, cycle, participant, billing_inputs, monthly_data):
        """Compute or update the expected bill for one GENCO."""
        contract = self._get_active_contract(participant, cycle)
        snapshot = cycle.rate_snapshot_ids.filtered(
            lambda s: s.participant_id == participant and s.is_current
        )[:1]

        if not snapshot:
            snapshot = self._compute_rate_snapshot(cycle, participant, billing_inputs)

        cap_rate = snapshot.capacity_rate
        eng_rate = snapshot.energy_rate
        hours = cycle.hours_in_period

        # Capacity charge: invoiced_capacity_mw × hours × capacity_rate
        cap_charge = 0.0
        cap_trace = {}
        if contract and contract.has_capacity_charge and monthly_data.invoiced_capacity_mw:
            cap_charge = monthly_data.invoiced_capacity_mw * hours * cap_rate
            cap_trace = {
                'qty_mw': monthly_data.invoiced_capacity_mw,
                'hours': hours,
                'rate': cap_rate,
                'charge': cap_charge,
            }

        # Energy charge: invoiced_energy_kwh × energy_rate
        eng_charge = 0.0
        eng_trace = {}
        if contract and contract.has_energy_charge and monthly_data.invoiced_energy_kwh:
            eng_charge = monthly_data.invoiced_energy_kwh * eng_rate
            eng_trace = {
                'qty_kwh': monthly_data.invoiced_energy_kwh,
                'rate': eng_rate,
                'charge': eng_charge,
            }

        # Import charge
        imp_charge = 0.0
        imp_trace = {}
        if monthly_data.has_import_liability:
            imp_charge, imp_trace = self._compute_import_charge(
                contract, cycle, monthly_data, billing_inputs, cap_rate, hours
            )

        total = cap_charge + eng_charge + imp_charge

        # Create / update expected bill
        ExpectedBill = self.env['nbet.genco.expected.bill']
        existing = ExpectedBill.search([
            ('billing_cycle_id', '=', cycle.id),
            ('participant_id', '=', participant.id),
        ], limit=1)

        bill_vals = {
            'billing_cycle_id': cycle.id,
            'participant_id': participant.id,
            'contract_id': contract.id if contract else False,
            'rate_snapshot_id': snapshot.id,
            'invoiced_capacity_mw': monthly_data.invoiced_capacity_mw,
            'invoiced_energy_kwh': monthly_data.invoiced_energy_kwh,
            'capacity_charge_amount': cap_charge,
            'energy_charge_amount': eng_charge,
            'import_charge_amount': imp_charge,
            'compute_date': fields.Datetime.now(),
            'state': 'computed',
            'currency_id': cycle.currency_id.id,
        }

        if existing:
            existing.write(bill_vals)
            bill = existing
        else:
            bill = ExpectedBill.create(bill_vals)

        # Rebuild bill lines
        bill.line_ids.unlink()
        lines_to_create = []
        if cap_charge:
            lines_to_create.append({
                'expected_bill_id': bill.id,
                'line_type': 'capacity',
                'description': f'Capacity Charge — {participant.name}',
                'quantity': monthly_data.invoiced_capacity_mw * hours,
                'rate': cap_rate,
                'amount': cap_charge,
                'formula_trace': json.dumps(cap_trace, indent=2, default=str),
                'sequence': 10,
            })
        if eng_charge:
            lines_to_create.append({
                'expected_bill_id': bill.id,
                'line_type': 'energy',
                'description': f'Energy Charge — {participant.name}',
                'quantity': monthly_data.invoiced_energy_kwh,
                'rate': eng_rate,
                'amount': eng_charge,
                'formula_trace': json.dumps(eng_trace, indent=2, default=str),
                'sequence': 20,
            })
        if imp_charge:
            lines_to_create.append({
                'expected_bill_id': bill.id,
                'line_type': 'import',
                'description': f'Import Liability Charge — {participant.name}',
                'quantity': monthly_data.import_excess_mw * hours,
                'rate': cap_rate,
                'amount': imp_charge,
                'formula_trace': json.dumps(imp_trace, indent=2, default=str),
                'sequence': 30,
            })
        if lines_to_create:
            self.env['nbet.genco.expected.bill.line'].create(lines_to_create)

        return bill

    def _compute_import_charge(self, contract, cycle, monthly_data, billing_inputs, cap_rate, hours):
        """Compute import liability charge when GENCO imports exceed supply.

        MAPPING NOTE: The exact rule for import charge treatment is:
        - If capacity_import_mw > capacity_sent_out_mw, the excess is treated
          as a DISCO liability at the GENCO's own capacity rate.
        - Confirm with NBET team whether energy import is also charged separately.
        """
        excess_mw = monthly_data.import_excess_mw
        import_charge = excess_mw * hours * cap_rate
        trace = {
            'rule': 'import_exceeds_supply',
            'capacity_sent_out_mw': monthly_data.capacity_sent_out_mw,
            'capacity_import_mw': monthly_data.capacity_import_mw,
            'excess_mw': excess_mw,
            'hours': hours,
            'cap_rate': cap_rate,
            'import_charge': import_charge,
        }
        return import_charge, trace

    # ──────────────────────────────────────────────────────────────────────────
    # DISCO Bill
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_disco_bill(self, cycle, participant, billing_inputs, disco_data):
        """Compute or update the DISCO bill for one DISCO."""
        # Fetch applicable DRO and freeze it
        dro = self._compute_dro_allocation(participant, cycle.date_start)
        dro_pct = dro.dro_percent

        # Freeze DRO on the operational data record
        disco_data.write({
            'applied_dro_id': dro.id,
            'applied_dro_percent': dro_pct,
        })

        # MAPPING NOTE: DISCO gross bill rate derivation — confirm with NBET team:
        # Option A: Use average of GENCO rates weighted by allocated energy
        # Option B: Use a NERC-published DISCO bulk supply tariff
        # Current implementation: use a simple tariff of ₦1/kWh capacity + ₦2/kWh energy
        # as a placeholder; REPLACE with actual DISCO bulk tariff logic.
        # This is clearly marked for replacement.
        # PLACEHOLDER RATES — replace with actual bulk supply tariff
        PLACEHOLDER_CAPACITY_RATE = 1000.0  # ₦/MW/h — REPLACE
        PLACEHOLDER_ENERGY_RATE = 3.5       # ₦/kWh — REPLACE

        hours = cycle.hours_in_period
        cap_charge = disco_data.capacity_delivered_mw * hours * PLACEHOLDER_CAPACITY_RATE
        eng_charge = disco_data.energy_delivered_kwh * PLACEHOLDER_ENERGY_RATE
        gross_bill = cap_charge + eng_charge

        expected_payable = gross_bill * dro_pct / 100.0
        subsidy_amount = gross_bill - expected_payable

        # Create / update DISCO bill
        DiscoBill = self.env['nbet.disco.bill']
        existing = DiscoBill.search([
            ('billing_cycle_id', '=', cycle.id),
            ('participant_id', '=', participant.id),
        ], limit=1)

        bill_vals = {
            'billing_cycle_id': cycle.id,
            'participant_id': participant.id,
            'capacity_delivered_mw': disco_data.capacity_delivered_mw,
            'energy_delivered_kwh': disco_data.energy_delivered_kwh,
            'applied_dro_id': dro.id,
            'applied_dro_percent': dro_pct,
            'expected_payable_amount': expected_payable,
            'subsidy_amount': subsidy_amount,
            'grant_amount': 0.0,
            'adjustment_amount': 0.0,
            'compute_date': fields.Datetime.now(),
            'state': 'computed',
            'currency_id': cycle.currency_id.id,
        }

        if existing:
            existing.write(bill_vals)
            bill = existing
        else:
            bill = DiscoBill.create(bill_vals)

        # Rebuild bill lines
        bill.line_ids.unlink()
        lines = []
        if cap_charge:
            lines.append({
                'disco_bill_id': bill.id,
                'line_type': 'capacity',
                'description': 'Capacity Charge',
                'quantity': disco_data.capacity_delivered_mw * hours,
                'rate': PLACEHOLDER_CAPACITY_RATE,
                'amount': cap_charge,
                'sequence': 10,
            })
        if eng_charge:
            lines.append({
                'disco_bill_id': bill.id,
                'line_type': 'energy',
                'description': 'Energy Charge',
                'quantity': disco_data.energy_delivered_kwh,
                'rate': PLACEHOLDER_ENERGY_RATE,
                'amount': eng_charge,
                'sequence': 20,
            })
        if subsidy_amount:
            lines.append({
                'disco_bill_id': bill.id,
                'line_type': 'subsidy',
                'description': f'Subsidy Offset (DRO {dro_pct:.2f}%)',
                'quantity': 1.0,
                'rate': -subsidy_amount,
                'amount': -subsidy_amount,
                'is_subsidy_line': True,
                'sequence': 50,
            })
        if lines:
            self.env['nbet.disco.bill.line'].create(lines)

        # Update operational data amounts
        disco_data.write({
            'expected_payable_amount': expected_payable,
            'subsidy_amount': subsidy_amount,
        })

        return bill

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_eval_context(self, contract, cycle, monthly_data, billing_inputs):
        """Build the safe_eval context dict for python_expression formula mode."""
        return {
            'base_capacity': contract.base_capacity_tariff if contract else 0.0,
            'base_energy': contract.base_energy_tariff if contract else 0.0,
            'fx_rate': billing_inputs.get('CBN_FX_CENTRAL', contract.base_fx_rate if contract else 1.0),
            'base_fx': contract.base_fx_rate if contract else 1.0,
            'tlf': billing_inputs.get('TLF_NEW', contract.base_tlf if contract else 1.0),
            'base_tlf': contract.base_tlf if contract else 1.0,
            'index': billing_inputs.get('AGIP_INDEX', contract.base_index_value if contract else 1.0),
            'base_index': contract.base_index_value if contract else 1.0,
            'hours': cycle.hours_in_period,
            'capacity_sent_out': monthly_data.capacity_sent_out_mw if monthly_data else 0.0,
            'net_energy': monthly_data.net_energy_kwh if monthly_data else 0.0,
            'invoiced_capacity': monthly_data.invoiced_capacity_mw if monthly_data else 0.0,
            'invoiced_energy': monthly_data.invoiced_energy_kwh if monthly_data else 0.0,
        }

    def _resolve_component_value(self, line, billing_inputs):
        """Resolve the value of a tariff component line."""
        if line.basis == 'fixed_value':
            return line.value
        elif line.basis == 'input_reference' and line.input_type_code:
            return billing_inputs.get(line.input_type_code, 0.0)
        elif line.basis == 'formula' and line.formula_expression:
            try:
                return float(safe_eval(line.formula_expression, locals_dict=billing_inputs))
            except Exception:
                return 0.0
        return 0.0

    def _log_run(self, cycle, run_type, genco_count, disco_count, errors, duration):
        """Create a billing run log entry."""
        status = 'success' if not errors else ('partial' if genco_count + disco_count > 0 else 'failed')
        self.env['nbet.billing.run.log'].create({
            'billing_cycle_id': cycle.id,
            'run_type': run_type,
            'status': status,
            'genco_records_affected': genco_count,
            'disco_records_affected': disco_count,
            'notes': f'Processed {genco_count} GENCO + {disco_count} DISCO records.',
            'error_log': '\n'.join(errors) if errors else False,
            'duration_seconds': duration,
        })
