# -*- coding: utf-8 -*-
{
    'name': 'NBET HR Leave Portal',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Time Off',
    'summary': 'Let employees request and track their time off from the portal',
    'description': """
NBET HR Leave Portal
====================
Gives employees a self-service Time Off area on the website portal so they can
log in as portal users and:

- Submit new time off / leave requests
- See the list and status of all their leave requests (To Approve, Approved, Refused...)
- Open any request to view its details
- See their remaining leave days per allocation type

All access is strictly scoped to the employee linked to the logged-in portal
user, so a portal user can only ever see and manage their own time off.
    """,
    'author': 'NBET Technical Team',
    'license': 'LGPL-3',
    'depends': [
        'hr_holidays',
        'portal',
    ],
    'data': [
        'views/portal_templates.xml',
        'views/hr_employee_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
