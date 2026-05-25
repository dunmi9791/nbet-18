# -*- coding: utf-8 -*-
{
    'name': 'NBET Power Billing – Excel Import',
    'version': '18.0.1.0.0',
    'summary': 'Excel and CSV import wizards for NBET monthly billing cycle data',
    'description': """
        Provides two import wizards for NBET billing data:
        1. Legacy Excel Workbook Import — parses the full NBET billing workbook
           (Inputs + Rates sheets) via openpyxl with fuzzy header matching.
        2. CSV/Excel Upload — structured upload using downloadable templates
           for three data categories: Billing Cycle Inputs, GENCO Operational
           Data, and DISCO Data.
        Both wizards stage data into a reviewable batch before committing.
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
        'wizard/csv_upload_wizard_views.xml',
        'views/import_batch_views.xml',
        'views/billing_cycle_inherit.xml',
        'views/menus.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
