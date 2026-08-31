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
        snapshots = cycle.rate_snapshot_ids.filtered(lambda s: s.is_current)
        wavg = self._compute_weighted_avg_rates(cycle, snapshots)
        count = 0
        errors = []
        for dd in cycle.disco_data_ids:
            try:
                self._compute_disco_bill(
                    cycle, dd.participant_id, billing_inputs, dd,
                    snapshots=snapshots, wavg=wavg,
                )
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

        elif mode == 'myto_components':
            rates = self._compute_myto_component_rates(contract, billing_inputs)
            rate = rates['capacity_rate']
            trace.update(rates['trace'])
            trace['result'] = rate

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
            lambda l: l.component_type_id.code == 'capacity' and l.active
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
                lambda l: l.component_type_id.code == 'energy' and l.basis == 'formula' and l.active
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
                lambda l: l.component_type_id.code == 'energy' and l.active
            ):
                val = self._resolve_component_value(line, billing_inputs)
                components.append({'name': line.name, 'value': val})
                rate += val
            trace['components'] = components
            trace['result'] = rate

        elif mode == 'myto_components':
            rates = self._compute_myto_component_rates(contract, billing_inputs)
            rate = rates['energy_rate']
            trace.update(rates['trace'])
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

    def _compute_weighted_avg_rates(self, cycle, snapshots=None):
        """Compute the weighted average of current GENCO rates for the cycle.

        Weights come from GENCO monthly operational data:
          - capacity rate weighted by invoiced_capacity_mw
          - energy rate weighted by invoiced_energy_kwh

        Returns:
            dict: {
                'capacity_rate': float, 'energy_rate': float,
                'cap_weight_total': float, 'eng_weight_total': float,
                'trace': dict,
            }
        Never raises: callers must check the weight totals before relying on
        a rate (a zero weight total means the rate is unavailable).
        """
        if snapshots is None:
            snapshots = cycle.rate_snapshot_ids.filtered(lambda s: s.is_current)
        cap_weighted_sum = 0.0
        cap_weight_total = 0.0
        eng_weighted_sum = 0.0
        eng_weight_total = 0.0
        components = []
        for snap in snapshots:
            gd = cycle.genco_data_ids.filtered(
                lambda d: d.participant_id == snap.participant_id
            )[:1]
            if not gd:
                continue
            cap_weighted_sum += snap.capacity_rate * gd.invoiced_capacity_mw
            cap_weight_total += gd.invoiced_capacity_mw
            eng_weighted_sum += snap.energy_rate * gd.invoiced_energy_kwh
            eng_weight_total += gd.invoiced_energy_kwh
            components.append({
                'genco': snap.participant_id.name,
                'capacity_rate': snap.capacity_rate,
                'invoiced_capacity_mw': gd.invoiced_capacity_mw,
                'energy_rate': snap.energy_rate,
                'invoiced_energy_kwh': gd.invoiced_energy_kwh,
            })
        cap_rate = cap_weighted_sum / cap_weight_total if cap_weight_total else 0.0
        eng_rate = eng_weighted_sum / eng_weight_total if eng_weight_total else 0.0
        return {
            'capacity_rate': cap_rate,
            'energy_rate': eng_rate,
            'cap_weight_total': cap_weight_total,
            'eng_weight_total': eng_weight_total,
            'trace': {
                'method': 'weighted_average_by_invoiced_quantities',
                'capacity_rate': cap_rate,
                'energy_rate': eng_rate,
                'components': components,
            },
        }

    def _compute_disco_bill(self, cycle, participant, billing_inputs, disco_data,
                            snapshots=None, wavg=None):
        """Compute or update the DISCO bill for one DISCO.

        The gross bill is split by the DISCO's GENCO allocation lines: each
        allocated percentage is billed at that GENCO's current snapshot rates,
        and any unallocated remainder is billed at the weighted average of
        GENCO rates for the cycle.
        """
        # Fetch applicable DRO and freeze it
        dro = self._compute_dro_allocation(participant, cycle.date_start)
        dro_pct = dro.dro_percent

        # Freeze DRO on the operational data record
        disco_data.write({
            'applied_dro_id': dro.id,
            'applied_dro_percent': dro_pct,
        })

        if snapshots is None:
            snapshots = cycle.rate_snapshot_ids.filtered(lambda s: s.is_current)
        if wavg is None:
            wavg = self._compute_weighted_avg_rates(cycle, snapshots)

        hours = cycle.hours_in_period
        charge_lines = []
        seq = 10
        total_pct = 0.0

        def _add_charge(line_type, description, quantity, rate, trace):
            nonlocal seq
            amount = quantity * rate
            if not amount:
                return 0.0
            charge_lines.append({
                'line_type': line_type,
                'description': description,
                'quantity': quantity,
                'rate': rate,
                'amount': amount,
                'formula_trace': json.dumps(trace, indent=2, default=str),
                'sequence': seq,
            })
            seq += 10
            return amount

        # Portions billed at specific GENCO rates
        for alloc in disco_data.allocation_line_ids:
            snap = snapshots.filtered(
                lambda s: s.participant_id == alloc.genco_id
            )[:1]
            if not snap:
                raise UserError(
                    f'No current rate snapshot for {alloc.genco_id.name} in cycle '
                    f'"{cycle.name}". Compute rates before computing DISCO bills.'
                )
            pct = alloc.allocation_percent
            total_pct += pct
            frac = pct / 100.0
            base_trace = {
                'rate_source': 'genco_snapshot',
                'genco': alloc.genco_id.name,
                'rate_snapshot_id': snap.id,
                'allocation_percent': pct,
            }
            _add_charge(
                'capacity',
                f'Capacity Charge — {pct:.2f}% @ {alloc.genco_id.name} rate',
                disco_data.capacity_delivered_mw * frac * hours,
                snap.capacity_rate,
                dict(base_trace,
                     capacity_delivered_mw=disco_data.capacity_delivered_mw,
                     hours=hours),
            )
            _add_charge(
                'energy',
                f'Energy Charge — {pct:.2f}% @ {alloc.genco_id.name} rate',
                disco_data.energy_delivered_kwh * frac,
                snap.energy_rate,
                dict(base_trace,
                     energy_delivered_kwh=disco_data.energy_delivered_kwh),
            )

        # Unallocated remainder billed at the weighted average of GENCO rates
        remainder_pct = max(0.0, 100.0 - total_pct)
        if remainder_pct > 1e-6:
            frac = remainder_pct / 100.0
            wavg_trace = dict(wavg['trace'], allocation_percent=remainder_pct)
            if disco_data.capacity_delivered_mw:
                if not wavg['cap_weight_total']:
                    raise UserError(
                        f'Cannot bill {participant.name}: the weighted average '
                        f'capacity rate is unavailable for cycle "{cycle.name}" '
                        '(no current GENCO rate snapshots with invoiced capacity). '
                        'Compute rates and load GENCO data first.'
                    )
                _add_charge(
                    'capacity',
                    f'Capacity Charge — {remainder_pct:.2f}% @ weighted avg GENCO rate',
                    disco_data.capacity_delivered_mw * frac * hours,
                    wavg['capacity_rate'],
                    dict(wavg_trace,
                         capacity_delivered_mw=disco_data.capacity_delivered_mw,
                         hours=hours),
                )
            if disco_data.energy_delivered_kwh:
                if not wavg['eng_weight_total']:
                    raise UserError(
                        f'Cannot bill {participant.name}: the weighted average '
                        f'energy rate is unavailable for cycle "{cycle.name}" '
                        '(no current GENCO rate snapshots with invoiced energy). '
                        'Compute rates and load GENCO data first.'
                    )
                _add_charge(
                    'energy',
                    f'Energy Charge — {remainder_pct:.2f}% @ weighted avg GENCO rate',
                    disco_data.energy_delivered_kwh * frac,
                    wavg['energy_rate'],
                    dict(wavg_trace,
                         energy_delivered_kwh=disco_data.energy_delivered_kwh),
                )

        gross_bill = sum(l['amount'] for l in charge_lines)
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
        lines = [dict(l, disco_bill_id=bill.id) for l in charge_lines]
        if subsidy_amount:
            lines.append({
                'disco_bill_id': bill.id,
                'line_type': 'subsidy',
                'description': f'Subsidy Offset (DRO {dro_pct:.2f}%)',
                'quantity': 1.0,
                'rate': -subsidy_amount,
                'amount': -subsidy_amount,
                'is_subsidy_line': True,
                'sequence': 50 + seq,
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

    def _compute_myto_component_rates(self, contract, billing_inputs):
        """Generic MYTO component engine — works for any plant type.

        Reads the contract's rate_param_ids to build an evaluation context:
          base_<code>    = param.base_value
          current_<code> = billing_inputs[param.billing_input_code] or param.base_value

        Then evaluates each active component line's formula_expression in sequence,
        accumulating computed values under the line's component_code so later lines
        (derived rows like Energy Charge, Capacity Charge) can reference earlier ones.

        Lines whose component_type is 'capacity' feed capacity_rate;
        lines whose component_type is 'energy' feed energy_rate.
        Returns dict with energy_rate, capacity_rate, wholesale_rate, and full trace.
        """
        # Build param context from contract's rate parameter table
        ctx = {}
        param_trace = []
        for param in contract.rate_param_ids:
            if not param.code:
                continue
            base_val = param.base_value
            current_val = (
                billing_inputs.get(param.billing_input_code, base_val)
                if param.billing_input_code
                else base_val
            )
            ctx[f'base_{param.code}'] = base_val
            ctx[f'current_{param.code}'] = current_val
            param_trace.append({
                'code': param.code,
                'name': param.name,
                'base': base_val,
                'current': current_val,
                'input_code': param.billing_input_code,
            })

        # Evaluate component lines in sequence order
        energy_rate = 0.0
        capacity_rate = 0.0
        wholesale_rate = 0.0
        component_trace = []

        for line in contract.line_ids.filtered(lambda l: l.active):
            if line.basis != 'formula' or not line.formula_expression:
                continue

            # Each line gets its own base_value in scope
            line_ctx = dict(ctx)
            line_ctx['base_value'] = line.base_value

            try:
                result = float(safe_eval(line.formula_expression, locals_dict=line_ctx))
            except Exception as exc:
                _logger.warning(
                    'MYTO component eval failed — line: %r | expr: %r | error: %s',
                    line.name, line.formula_expression, exc,
                )
                result = 0.0

            # Accumulate under the component code so subsequent lines can reference it
            if line.component_code:
                ctx[line.component_code] = result

            comp_type = line.component_type or ''
            if comp_type == 'capacity':
                capacity_rate += result
            elif comp_type == 'energy':
                energy_rate += result
            elif comp_type == 'wholesale':
                wholesale_rate = result

            component_trace.append({
                'name': line.name,
                'code': line.component_code,
                'type': comp_type,
                'base_value': line.base_value,
                'expression': line.formula_expression,
                'result': result,
            })

        if not wholesale_rate:
            wholesale_rate = energy_rate + capacity_rate

        return {
            'energy_rate': energy_rate,
            'capacity_rate': capacity_rate,
            'wholesale_rate': wholesale_rate,
            'trace': {
                'mode': 'myto_components',
                'params': param_trace,
                'components': component_trace,
            },
        }

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
