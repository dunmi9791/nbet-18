# -*- coding: utf-8 -*-
{
    'name': 'NBET Treasury',
    'version': '18.0.1.0.0',
    'category': 'Accounting/NBET',
    'summary': 'Treasury payment scheduling and management for NBET',
    'description': """
NBET Treasury Management
=========================
Manages payment scheduling and processing for approved payment requests
from the Procurement module, including:

- Dashboard with payment pipeline visualization and KPIs
- Segregated approval workflow (Scheduled → CFO → Finance Manager → Vouchers →
  Audit Review → Audit Approval → Paid)
- Dedicated CFO, Finance Manager and Auditor approval authorities
- Payment vouchers raised by the assigned finance officer, carrying the voucher
  number, transaction reference, payee details, amount, full approval history and
  HMAC digital authentication records with date/time stamps
- Automatic tax remittance vouchers (VAT, WHT) to the relevant tax body
- Configurable statutory deduction rules (per contract category) that pre-fill
  the deductions on new payment schedules
- Two-person audit: one auditor reviews, a different auditor approves
- Segregation-of-duties enforcement across approval stages
- Payment method tracking (Bank Transfer, Cheque, Bank Draft)
- Hold/resume capability for scheduled payments
- Automatic status update on source documents when paid
- Payment sources are pluggable: procurement payment requests out of the box,
  payroll batches once NBET Payroll Treasury is installed
- Bulk payment registration: settle every audited voucher on a schedule against
  one bank instruction reference
- Priority-based payment queue management
- Treasury Report: balances of all active bank accounts with the inflow and
  outflow of each summarised by day, week or month over any date range
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'account',
        'nbet_procurement',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'reports/payment_voucher_report.xml',
        'reports/treasury_report.xml',
        'views/tax_rule_views.xml',
        'views/payment_schedule_views.xml',
        'views/payment_voucher_views.xml',
        'views/payment_request_inherit_views.xml',
        'views/dashboard_views.xml',
        'wizard/treasury_report_views.xml',
        'wizard/voucher_payment_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nbet_treasury/static/src/scss/treasury.scss',
            'nbet_treasury/static/src/js/treasury_dashboard.js',
            'nbet_treasury/static/src/xml/treasury_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
