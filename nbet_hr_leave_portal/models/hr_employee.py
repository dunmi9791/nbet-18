# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def action_grant_leave_portal_access(self):
        """Open the standard "Grant Portal Access" wizard for this employee.

        The wizard works on the employee's contact (res.partner), letting HR
        invite the person as a portal user so they can use the Time Off portal.
        """
        self.ensure_one()
        partner = self.work_contact_id or self.user_id.partner_id
        if not partner:
            raise UserError(_(
                "This employee has no related contact or user. Set a Work "
                "Contact or a Related User before granting portal access."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Grant Portal Access'),
            'res_model': 'portal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'res.partner',
                'active_ids': partner.ids,
                'active_id': partner.id,
            },
        }
