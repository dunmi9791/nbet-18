# -*- coding: utf-8 -*-
{
    'name': 'NBET Billing Treasury',
    'version': '18.0.1.0.0',
    'category': 'Accounting/NBET',
    'summary': 'Route approved GENCO payment advices through the treasury voucher chain',
    'description': """
NBET Billing Treasury
=====================
Carries an approved GENCO payment advice from power billing into the treasury
payment chain:

- After the Payment Committee meeting, billing raises a payment advice sharing
  the cycle's collections across the GENCOs, approved by the Head of OCMA and
  then the Managing Director
- On MD approval the advice is sent to Treasury, which raises a single payment
  schedule for the whole advice
- The schedule follows the standard treasury chain: CFO approval, Finance
  Manager approval, vouchers raised by the assigned finance officer, two-person
  audit, then payment
- One payment voucher is raised per GENCO for the amount advised to it
- Paying a GENCO's voucher reconciles it against the cycle's vendor bills;
  when every voucher on the schedule is paid the advice is marked paid
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'nbet_power_billing',
        'nbet_treasury',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_advice_views.xml',
        'views/payment_schedule_views.xml',
        'views/payment_voucher_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
