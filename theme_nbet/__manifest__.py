# -*- coding: utf-8 -*-
{
    'name': 'NBET Theme',
    'description': 'NBET corporate website theme',
    'category': 'Theme/Corporate',
    'summary': 'Energy, Utility, Government, Corporate, Power Sector',
    'sequence': 190,
    'version': '18.0.1.0.0',
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'website',
        'portal',
    ],
    'data': [
        'data/ir_asset.xml',

        'views/snippets/s_nbet_hero.xml',
        'views/snippets/s_nbet_quicklinks.xml',
        'views/snippets/s_nbet_capacity.xml',
        'views/snippets/s_nbet_value_chain.xml',
        'views/snippets/s_nbet_partners.xml',
        'views/snippets/s_nbet_leadership.xml',
        'views/snippets/snippets.xml',

        'views/layout.xml',
        'views/login.xml',
        'views/portal.xml',

        'data/pages.xml',
    ],
    'images': [
        'static/description/cover.png',
    ],
    # No 'configurator_snippets' on purpose.
    #
    # That key only works for snippets that already exist as ir.ui.view records
    # (i.e. website.* ones). For a theme's own snippets it resolves the xmlid to
    # a theme.ir.ui.view id and assigns it to ir.ui.view.inherit_id — see
    # get_create_vals() in website/models/ir_module_module.py, which uses
    # parent_id[1] without checking the model. Enterprise themes sidestep this
    # by overriding website.* snippets rather than declaring new keys.
    #
    # The homepage is populated directly by data/pages.xml instead, which is the
    # stronger mechanism anyway: it applies on install, not only when someone
    # runs the website configurator.
    'installable': True,
    'application': False,
    'auto_install': False,
}
