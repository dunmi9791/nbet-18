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
- Multi-step approval workflow (Scheduled → Reviewed → Verified → Approved → Paid)
- Payment method tracking (Bank Transfer, Cheque, Bank Draft)
- Hold/resume capability for scheduled payments
- Automatic status update on source documents when paid
- Priority-based payment queue management
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
        'views/payment_request_inherit_views.xml',
        'views/dashboard_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nbet_treasury/static/src/js/treasury_dashboard.js',
            'nbet_treasury/static/src/xml/treasury_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
