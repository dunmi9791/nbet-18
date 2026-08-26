# -*- coding: utf-8 -*-
{
    'name': 'NBET Payroll Treasury',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Route processed payroll batches through MD approval and the treasury voucher chain',
    'description': """
NBET Payroll Treasury
=====================
Carries a processed payroll batch from payroll into the treasury payment chain:

- Once the payslips of a batch are validated, the batch is submitted to the
  Managing Director for approval
- On MD approval the batch is sent to Treasury, which raises a single payment
  schedule for the whole batch
- The schedule follows the standard treasury chain: CFO approval, Finance
  Manager approval, vouchers raised by the assigned finance officer, two-person
  audit, then payment
- One payment voucher is raised per payslip (the employee's net pay), plus one
  remittance voucher per statutory deduction body (PAYE, pension, NHF ...),
  grouped by the configured payroll deduction rules
- Marking an employee's voucher paid marks that payslip paid in payroll; when
  every voucher on the schedule is paid the whole batch is marked paid
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'hr_payroll',
        'hr_payroll_account',
        'nbet_treasury',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'views/payroll_deduction_rule_views.xml',
        'views/hr_payslip_run_views.xml',
        'views/hr_payslip_views.xml',
        'views/payment_schedule_views.xml',
        'views/payment_voucher_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
