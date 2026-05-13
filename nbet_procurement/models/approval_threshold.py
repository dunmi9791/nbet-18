# -*- coding: utf-8 -*-
from odoo import models, fields


class ApprovalThreshold(models.Model):
    _name = 'nbet.approval.threshold'
    _description = 'Procurement Approval Threshold'
    _order = 'min_amount'

    name = fields.Char(required=True)
    authority = fields.Selection([
        ('md_ceo', 'MD/CEO'),
        ('ptb', 'Parastatal Tenders Board (PTB)'),
        ('mtb', 'Ministerial Tenders Board (MTB)'),
        ('fec_bpp', 'FEC / BPP No Objection'),
    ], required=True, string='Approving Authority')
    category = fields.Selection([
        ('goods', 'Goods'),
        ('works', 'Works'),
        ('non_consultant', 'Non-Consultant Services'),
        ('consultant', 'Consultant Services'),
    ], required=True)
    min_amount = fields.Float(string='Minimum Amount (NGN)')
    max_amount = fields.Float(string='Maximum Amount (NGN)', help='0 = no upper limit')
    active = fields.Boolean(default=True)
