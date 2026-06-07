# -*- coding: utf-8 -*-
{
    'name': 'NBET Procurement Management',
    'version': '18.0.1.0.0',
    'category': 'Purchases/NBET',
    'summary': 'Customizes Purchase module to implement NBET Procurement SOP',
    'description': """
NBET Procurement Management
============================
Implements the NBET Standard Operating Procedure for procurement of Goods,
Works and Services, including:

- Multi-stage procurement workflow (Needs Assessment -> Planning -> Bidding -> Award -> Delivery -> Payment)
- Procurement Planning Committee (PPC) and Parastatal Tenders Board (PTB) approvals
- Approval thresholds per Public Procurement Act 2007 (MD/CEO, PTB, MTB, FEC/BPP)
- Procurement method auto-selection based on value (Shopping, RFQ, NCB, ICB, Single Source)
- Tender Evaluation Committee (TEC) bid evaluation tracking
- Contract award and agreement workflow
- Goods/services verification and inspection
- Needs assessment and budget allocation tracking
- BPP NOCOPO portal compliance
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'hr',
        'purchase',
        'product',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/procurement_method_data.xml',
        'data/approval_threshold_data.xml',
        'wizard/submit_for_approval_views.xml',
        'views/needs_assessment_views.xml',
        'views/procurement_plan_views.xml',
        'views/bid_evaluation_views.xml',
        'views/contract_award_views.xml',
        'views/purchase_order_views.xml',
        'views/payment_request_views.xml',
        'views/dashboard_views.xml',
        'views/menus.xml',
        'reports/procurement_plan_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nbet_procurement/static/src/js/procurement_dashboard.js',
            'nbet_procurement/static/src/xml/procurement_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
