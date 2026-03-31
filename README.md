# NBET Power Billing — Odoo 18 Module Suite

Production-grade Odoo 18 modules for managing the Nigerian Bulk Electricity Trading (NBET) monthly power settlement and billing cycle.

---

## Module Suite

| Module | Purpose |
|---|---|
| `nbet_power_billing` | Core module — master data, billing cycle, rate engine, calculations, accounting |
| `nbet_power_billing_account` | Accounting settings tab in Odoo Settings |
| `nbet_power_billing_import` | Excel import wizard for legacy NBET workbook migration |

---

## Architecture Overview

```
nbet_power_billing/
├── models/
│   ├── market_participant.py       # nbet.market.participant (GENCO/DISCO/TSO/other)
│   ├── genco_contract.py           # nbet.genco.contract — rate structure
│   ├── genco_contract_line.py      # nbet.genco.contract.line — tariff components
│   ├── disco_dro.py                # nbet.disco.dro — DRO history with overlap guard
│   ├── billing_input_type.py       # nbet.billing.input.type — input catalog
│   ├── billing_cycle.py            # nbet.billing.cycle — master control record
│   ├── billing_cycle_input.py      # nbet.billing.cycle.input — auditable inputs
│   ├── billing_run_log.py          # nbet.billing.run.log — calc run audit trail
│   ├── genco_monthly_data.py       # nbet.genco.monthly.data — operational data
│   ├── disco_monthly_data.py       # nbet.disco.monthly.data
│   ├── rate_snapshot.py            # nbet.rate.snapshot — frozen rate record + trace
│   ├── calculation_service.py      # nbet.calculation.service — calc engine
│   ├── genco_expected_bill.py      # nbet.genco.expected.bill + lines
│   ├── genco_invoice_submission.py # nbet.genco.invoice.submission + comparison
│   ├── disco_bill.py               # nbet.disco.bill + lines
│   ├── billing_adjustment.py       # nbet.billing.adjustment
│   ├── billing_config.py           # nbet.billing.config (per-company)
│   └── accounting_service.py       # nbet.accounting.service — Odoo move creation
├── views/                          # All XML view files
├── security/                       # Groups + access CSV
├── data/                           # Seed data (billing input types)
├── demo/                           # Demo GENCOs, DISCOs, April 2024 cycle
├── reports/                        # QWeb PDF reports
├── tests/                          # Unit tests
└── wizard/                         # (import wizard lives in nbet_power_billing_import)

nbet_power_billing_account/
├── models/res_config_settings.py   # Settings tab via ICP
└── views/res_config_settings_views.xml

nbet_power_billing_import/
├── models/import_batch.py          # nbet.import.batch + lines + error log
└── wizard/excel_import_wizard.py   # TransientModel with openpyxl parsing
```

---

## Prerequisites

- Odoo 18.0 (Community or Enterprise)
- Python package: `openpyxl` (for the Excel import module)

```bash
pip install openpyxl
```

---

## Installation

1. Copy all three module folders into your Odoo `addons` path.
2. Update the apps list: **Settings → Apps → Update Apps List**
3. Install in this order:
   - `nbet_power_billing` (core)
   - `nbet_power_billing_account` (accounting settings)
   - `nbet_power_billing_import` (Excel import, requires `openpyxl`)

---

## First-Time Configuration

### 1. Accounting Accounts
Go to **Settings → NBET Power Billing** and configure:
- Revenue accounts (capacity, energy)
- Expense accounts (capacity, energy)
- Subsidy and grant receivable accounts
- Adjustment and import charge accounts
- Journals (GENCO payable, DISCO receivable, subsidy/grant)

### 2. DISCO Invoice Mode
Choose from three modes:
- **DRO Only** *(default)*: Invoice DISCO for their DRO portion. Subsidy tracked in reports.
- **Full + Credit Note**: Invoice full gross, post subsidy as credit note.
- **DRO + Subsidy Receivable**: Invoice DRO portion; create separate receivable for subsidy against the configured subsidy sponsor partner.

### 3. Variance Tolerance
Set the tolerance percentage (default 1%) for GENCO invoice comparison.

---

## Billing Cycle Workflow

### Step-by-step

```
Draft
  │
  ├─► [Load Inputs / Import from Excel]
  │       ↓
  │   input_loaded
  │
  ├─► [Compute Rates]
  │       ↓
  │   calculated
  │
  ├─► [Review GENCO Bills & Submitted Invoices]
  │       ↓
  │   reviewed
  │
  ├─► [Approve] (Settlement Manager)
  │       ↓
  │   approved
  │
  ├─► [Post Accounting] (Accounting Officer)
  │       ↓
  │   posted
  │
  └─► [Lock] (Administrator)
          ↓
        locked
```

1. **Create Billing Cycle** — Set period dates, hours in month, TLF values, FX rates.
2. **Import from Excel** — Use the Excel import wizard (NBET Power Billing → Import → Import from Excel) to parse the legacy workbook. Preview staged data before confirming.
3. **Enter Operational Data** — Manually review/add GENCO monthly data (capacity sent out, energy, imports) and DISCO delivered data.
4. **Compute Rates** — Click "Compute Rates" to create `nbet.rate.snapshot` records for each GENCO. Each snapshot stores the exact rates and a JSON formula trace.
5. **Compute GENCO Bills** — Click "Compute GENCO Bills" to create `nbet.genco.expected.bill` records.
6. **Load GENCO Invoices** — Enter submitted GENCO invoice values and click "Compare" to generate comparison lines and flag variances.
7. **Compute DISCO Bills** — Click "Compute DISCO Bills". The system fetches the correct DRO history record by effective date and freezes the DRO% on the bill.
8. **Approve** — Settlement Manager approves the cycle.
9. **Post Accounting** — Accounting Officer triggers accounting document creation (vendor bills for GENCOs, customer invoices for DISCOs, adjustment entries).
10. **Lock** — Administrator locks the cycle to prevent any further changes.

---

## Security Groups

| Group | Capabilities |
|---|---|
| **NBET Billing Officer** | Create/edit cycles, import data, compute bills |
| **NBET Billing Reviewer** | Review bills, flag variances (inherits Officer) |
| **NBET Settlement Manager** | Approve settlements, manage DRO records (inherits Reviewer) |
| **NBET Accounting Officer** | Post accounting documents (inherits Manager) |
| **NBET Administrator** | Full access, reset locked cycles, delete records |

---

## Rate Engine

The calculation service (`nbet.calculation.service`) supports four formula modes per GENCO contract:

| Mode | Description |
|---|---|
| `fixed` | Returns `base_capacity_tariff` / `base_energy_tariff` unchanged |
| `parametric` | Applies FX, TLF, and index adjustments using ratios vs base values |
| `python_expression` | Evaluates a stored Python expression with a safe context dict |
| `structured_components` | Sums up tariff component lines (most flexible) |

### Parametric adjustment example
```
adjusted_capacity_rate = base_capacity_tariff
    × (fx_rate / base_fx_rate)         # if uses_fx_adjustment
    × (tlf / base_tlf)                 # if uses_tlf_adjustment
    × (index / base_index_value)        # if uses_index_adjustment
```

### Safe eval context for python_expression mode
```python
{
    'base_capacity': contract.base_capacity_tariff,
    'base_energy': contract.base_energy_tariff,
    'fx_rate': billing_inputs['CBN_FX_CENTRAL'],
    'base_fx': contract.base_fx_rate,
    'tlf': billing_inputs['TLF_NEW'],
    'base_tlf': contract.base_tlf,
    'index': billing_inputs['AGIP_INDEX'],
    'base_index': contract.base_index_value,
    'hours': cycle.hours_in_period,
    'capacity_sent_out': monthly_data.capacity_sent_out_mw,
    'net_energy': monthly_data.net_energy_kwh,
}
```

---

## DRO History

- DRO records for each DISCO store `effective_from` / `effective_to` date ranges.
- The system enforces **no overlapping active date ranges** for the same DISCO.
- When computing a DISCO bill, the system fetches the DRO record whose date range covers `billing_cycle.date_start`.
- The `applied_dro_percent` is **frozen** on the DISCO bill at computation time. Future DRO changes do not alter posted bills.

---

## Excel Import Mapping Reference

The import wizard (`nbet_power_billing_import`) parses the legacy NBET Excel workbook.

### "Inputs" Sheet

| Expected Label (fuzzy match) | Maps to Input Code | Target Field |
|---|---|---|
| CBN Central Rate / FX Central | `CBN_FX_CENTRAL` | `nbet.billing.cycle.input` |
| CBN Selling Rate / FX Selling | `CBN_FX_SELLING` | `nbet.billing.cycle.input` |
| TLF Old / Old TLF | `TLF_OLD` | `nbet.billing.cycle.input` |
| TLF New / New TLF | `TLF_NEW` | `nbet.billing.cycle.input` |
| Hours in Month | `HOURS_IN_MONTH` | `nbet.billing.cycle.input` |
| Agip Index / Quarterly Index | `AGIP_INDEX` | `nbet.billing.cycle.input` |
| Capacity Sent Out (MW) | — | `nbet.genco.monthly.data.capacity_sent_out_mw` |
| Gross Energy (kWh/GWh) | — | `nbet.genco.monthly.data.gross_energy_kwh` |
| Net Energy | — | `nbet.genco.monthly.data.net_energy_kwh` |
| Import Capacity / Capacity Import | — | `nbet.genco.monthly.data.capacity_import_mw` |
| Import Energy | — | `nbet.genco.monthly.data.energy_import_kwh` |
| Invoiced Capacity | — | `nbet.genco.monthly.data.invoiced_capacity_mw` |
| Invoiced Energy | — | `nbet.genco.monthly.data.invoiced_energy_kwh` |

**Unit handling**: Values in GWh are auto-converted to kWh (×1,000,000).

### "Rates" Sheet

| Expected Column Header | Maps to |
|---|---|
| GENCO / Plant Name | `nbet.market.participant` (fuzzy match) |
| Capacity Rate | `nbet.rate.snapshot.capacity_rate` |
| Energy Rate | `nbet.rate.snapshot.energy_rate` |
| Applied FX | `nbet.rate.snapshot.fx_rate_used` |
| Applied TLF | `nbet.rate.snapshot.tlf_used` |
| Applied Index | `nbet.rate.snapshot.index_value_used` |

> **⚠ Ambiguity Note**: The exact row/column layout of the legacy workbook varies by period. If your workbook differs from the default layout, you can:
> 1. Override the sheet name in the wizard (default: `Inputs`, `Rates`)
> 2. Edit the `_parse_inputs_sheet` / `_parse_rates_sheet` methods in `excel_import_wizard.py`
> 3. Import raw staged lines and correct them manually before confirming

---

## Accounting Modes (DISCO Invoice)

### Mode 1 — DRO Only (default)
```
Customer Invoice (DISCO):
  Capacity Revenue   Dr DISCO Receivable   Cr Capacity Revenue
  Energy Revenue     Dr DISCO Receivable   Cr Energy Revenue
  Amount = gross × DRO%
  Subsidy tracked in operational report only.
```

### Mode 2 — Full + Credit Note
```
Customer Invoice (DISCO, full gross):
  Dr DISCO Receivable   Cr Capacity Revenue / Energy Revenue
  Amount = gross

Credit Note (subsidy):
  Dr Subsidy Receivable   Cr DISCO Receivable
  Amount = gross × (1 - DRO%)
```

### Mode 3 — DRO Invoice + Subsidy Receivable
```
Customer Invoice (DISCO, DRO portion):
  Dr DISCO Receivable   Cr Revenue
  Amount = gross × DRO%

Journal Entry (subsidy sponsor):
  Dr Subsidy Receivable (Gov Partner)   Cr Revenue
  Amount = gross × (1 - DRO%)
```

---

## Reports

| Report | Format | Access |
|---|---|---|
| Monthly GENCO Settlement Schedule | PDF / printable | All officers |
| DISCO Billing Schedule | PDF / printable | All officers |
| Cycle Summary | PDF | Reviewers+ |
| GENCO Variance Report | Via list view export | Officers |
| DRO Application Report | Via list view export | Officers |

---

## Running Tests

```bash
python odoo-bin -d <database> --test-enable --test-tags /nbet_power_billing -u nbet_power_billing
```

---

## Demo Data

Installing with demo data (`--without-demo=` not set) creates:

- 4 GENCOs: Egbin (gas), Kainji (hydro), Afam (gas), Transcorp (NIPP)
- 4 DISCOs: IBEDC, EKEDC, IKEDC, KEDCO
- DRO history for each DISCO with 2023 and 2024 records
- April 2024 billing cycle with:
  - Cycle inputs (FX, TLF, hours, Agip index)
  - GENCO monthly operational data (including Transcorp with import > supply)
  - DISCO monthly delivered data with DRO applied

---

## Known Limitations / Future Work

1. **Python expression formula mode**: Uses `safe_eval` but is still a code-execution path. Only administrator-level users should configure formula expressions.
2. **Gas price / quarterly index derivation**: The Agip gas index and its application to gas GENCO rates depends on contract-specific rules not visible in the sample workbook. Mark formula components with `# MAPPING: verify with NBET team` comments.
3. **MYTO tariff reviews**: When NERC issues a MYTO review order, base rates must be updated on contracts. The system handles this via contract versioning (new contract record with new dates), not in-place rate changes.
4. **FX settlement lag**: Some contracts use FX rate from a previous month or CBN average. Configure via `nbet.billing.cycle.input` for the specific `CBN_FX_CENTRAL` / `CBN_FX_SELLING` values for each cycle.
5. **Analytic accounting**: Full analytic dimension tagging is available but requires `account_analytic_accounting` or equivalent to be installed and `nbet_create_analytic_tags` to be enabled in settings.

---

## Support

For questions on rate formula mappings, contact the NBET Technical Settlement Team.
For Odoo-specific issues, open a ticket with the relevant billing cycle code and participant name.
