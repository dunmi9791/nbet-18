# -*- coding: utf-8 -*-
{
    'name': 'NBET Power Billing – Excel Import',
    'version': '18.0.1.0.0',
    'summary': 'Excel import wizard for NBET monthly billing cycle inputs',
    'description': """
        Provides an openpyxl-based Excel import wizard that reads the legacy
        NBET billing workbook (Inputs sheet + Rates sheet), stages the data
        into a reviewable batch, and commits it into the core billing models
        on confirmation.
    """,
    'author': 'NBET IT',
    'category': 'Accounting/Localization',
    'license': 'LGPL-3',
    'depends': ['nbet_power_billing'],
    'external_dependencies': {
        'python': ['openpyxl'],
    },
    'data': [
        'security/ir.model.access.csv',
        'wizard/excel_import_wizard_views.xml',
        'views/import_batch_views.xml',
        'views/menus.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
