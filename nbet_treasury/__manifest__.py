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

- Payment schedule queue with priority management
- Payment method tracking (Bank Transfer, Cheque, Bank Draft)
- Payment processing workflow (Pending → Scheduled → Processing → Paid)
- Hold/resume capability for scheduled payments
- Integration with Procurement Payment Requests
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'nbet_procurement',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'views/payment_schedule_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
