# -*- coding: utf-8 -*-
{
    'name': 'NBET NISO Advice & Receipt Management',
    'version': '18.0.1.0.0',
    'category': 'Accounting/NBET',
    'summary': 'Tracks NISO monthly admin charge advices and the receipts drawn down against them',
    'description': """
NBET NISO Advice & Receipt Management
=====================================
NISO advises NBET each month of the administrative charge due to NBET for that
month. The advice is a receivable from NISO, and it is drawn down as payments
are received against it.

- Monthly admin charge advices, one per period, with the amount advised by NISO
- Confirming an advice raises the receivable: a customer invoice is posted
  against NISO on the configured admin charge income account
- Receipts recorded against an advice post an inbound payment and reconcile it
  against the advice's invoice, so the ledger and the module agree
- Live draw-down tracking per advice: advised, received and outstanding, with
  the state moving Confirmed -> Partially Received -> Fully Received
- Receipts cannot exceed the outstanding balance of the advice they draw down
- Outstanding-per-period reporting and an ageing view of unsettled advices
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'account',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'views/niso_advice_views.xml',
        'views/niso_receipt_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
