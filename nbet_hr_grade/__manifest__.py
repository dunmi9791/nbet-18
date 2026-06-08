# -*- coding: utf-8 -*-
{
    'name': 'NBET Employee Grade & Step',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/NBET',
    'summary': 'Grade and step/rank-based salary structure for employees',
    'description': """
NBET Employee Grade & Step Management
=======================================
Manages employee salary grades and steps (ranks) following the Nigerian
consolidated salary structure pattern:

- Define salary grades (e.g., GL-01 to GL-17)
- Each grade has multiple steps with a specific salary amount
- Assign grade and step to employees
- Auto-populate contract wage from the employee's current grade/step
- Salary amounts on grades/steps can be updated over time
- Full audit trail via chatter
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'hr',
        'hr_contract',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'views/hr_grade_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_contract_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
