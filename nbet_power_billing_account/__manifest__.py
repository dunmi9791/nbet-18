# -*- coding: utf-8 -*-
{
    'name': 'NBET Power Billing – Accounting Integration',
    'version': '18.0.1.0.0',
    'summary': 'Accounting configuration and journal entry generation for NBET settlement',
    'description': """
        Extends res.config.settings with NBET-specific accounting configuration:
        journal assignments, revenue/payable/subsidy accounts, and DISCO invoice
        mode selection.  The accounting service (nbet.accounting.service) uses
        these settings to auto-generate vendor bills, customer invoices, credit
        notes, and journal entries when a billing cycle is posted.
    """,
    'author': 'NBET IT',
    'category': 'Accounting/Localization',
    'license': 'LGPL-3',
    'depends': [
        'nbet_power_billing',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
