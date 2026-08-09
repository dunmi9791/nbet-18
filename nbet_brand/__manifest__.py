# -*- coding: utf-8 -*-
{
    'name': 'NBET Branding',
    'version': '18.0.1.0.0',
    'category': 'Technical',
    'summary': 'NBET PDF letterhead for QWeb reports',
    'description': """
NBET Branding
=============
Registers an "NBET" document layout (Settings > General Settings > Document
Layout) carrying the navy/lime masthead rule from the corporate site.

Because it plugs into ``web.external_layout``, every QWeb report picks it up
without being touched individually — the ``nbet_treasury`` payment vouchers,
``nbet_procurement`` purchase orders, invoices, and anything added later.

Deliberately kept separate from ``theme_nbet``. Odoo converts every template in
a module named ``theme_*`` into a ``theme.ir.ui.view``, which is copied per
website and removed when the theme is switched out. ``report.layout.view_id``
is a many2one to ``ir.ui.view``, so a reference to a template declared in a
theme module would point at the wrong table and fail to load.

Depends only on ``web``: reports are not website-scoped, so this installs on
any database, with or without ``theme_nbet``.
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'web',
    ],
    'data': [
        'views/report_layout.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'nbet_brand/static/src/scss/report.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
