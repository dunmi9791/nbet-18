# -*- coding: utf-8 -*-
{
    'name': 'NBET Power Billing',
    'version': '18.0.1.0.0',
    'category': 'Accounting/NBET',
    'summary': 'NBET Monthly Power Settlement and Billing Management',
    'description': """
        Manages the full NBET monthly billing cycle for the Nigerian electricity market:
        - GENCO and DISCO market participant master data
        - GENCO contract/rate structure with MYTO formulas (fixed, parametric, python, component)
        - Monthly operational data capture (manual or Excel import)
        - GENCO expected bill computation with full rate snapshot and trace
        - GENCO submitted invoice comparison and variance analysis
        - DISCO billing with DRO-based payable calculation (DRO frozen at billing time)
        - Subsidy/grant exposure tracking
        - Full audit trail, approvals workflow, and run log
        - Odoo Accounting integration (vendor bills, customer invoices, journal entries)
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'account',
        'analytic',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/billing_input_types.xml',
        'views/market_participant_views.xml',
        'views/genco_contract_views.xml',
        'views/disco_dro_views.xml',
        'views/billing_input_type_views.xml',
        'views/billing_cycle_views.xml',
        'views/genco_monthly_data_views.xml',
        'views/disco_monthly_data_views.xml',
        'views/rate_snapshot_views.xml',
        'views/genco_expected_bill_views.xml',
        'views/genco_invoice_submission_views.xml',
        'views/disco_bill_views.xml',
        'views/billing_adjustment_views.xml',
        'views/billing_config_views.xml',
        'reports/report_genco_settlement.xml',
        'reports/report_disco_billing.xml',
        'reports/report_cycle_summary.xml',
        'views/menus.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'sequence': 200,
}
