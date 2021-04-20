from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockBundle(models.Model):
    _name = 'stock.bundle'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Bundle Product'

    name = fields.Char(string='Bundle Reference', required=True,
                       copy=False, default='New')
    warehouse_id = fields.Many2one(
        'stock.warehouse', 'Warehouse', required=True)
    product_id = fields.Many2one(
        'product.product', 'Finished Goods', required=True)
    uom_id = fields.Many2one('uom.uom', 'UoM', required=True)
    product_uom_qty = fields.Float('Qty', required=True)
    line_ids = fields.One2many(
        'stock.bundle.line', 'bundle_id', 'Product to Bundle', copy=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('cancel', 'Cancelled'),
        ('done', 'Done')],
        'Status', track_visibility='onchange', required=True, copy=False, default='draft')
    picking_out_id = fields.Many2one(
        'stock.picking', 'Picking Out', copy=False)
    picking_in_id = fields.Many2one('stock.picking', 'Picking In', copy=False)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code(
                'stock.bundle') or '/'
        return super(StockBundle, self).create(vals)

    @api.multi
    def unlink(self):
        if any(s == 'done' for s in self.mapped('state')):
            raise UserError(_('Unable to delete finished bundle!'))
        return super(StockBundle, self).unlink()

    @api.onchange('product_id')
    def onchange_product(self):
        self.uom_id = self.product_id.uom_id.id

    @api.multi
    def action_done(self):
        for bundle in self:
            transit_location = self.env['stock.location'].search(
                [('usage', '=', 'production')], limit=1)
            if not transit_location:
                raise UserError(
                    _('Please define production location in location settings!'))
            bundle.state = 'done'
            bundle.picking_out_id = self.env['stock.picking'].create({
                'picking_type_id': bundle.warehouse_id.out_type_id.id,
                'origin': bundle.name,
                'move_type': 'direct',
                'location_id': bundle.warehouse_id.out_type_id.default_location_src_id.id,
                'location_dest_id': transit_location.id,
                'company_id': bundle.warehouse_id.company_id.id,
                'move_lines': [(0, 0, {
                    'product_id': line.product_id.id,
                    'product_uom': line.uom_id.id,
                    'name': str(line.product_id.display_name),
                    'product_uom_qty': line.product_uom_qty,
                    'quantity_done': line.product_uom_qty,
                    'company_id': bundle.warehouse_id.company_id.id,
                }) for line in bundle.line_ids]
            }).id
            bundle.picking_out_id.action_confirm()
            bundle.picking_out_id.action_assign()
            if bundle.picking_out_id.state != 'assigned':
                raise UserError(_("Insufficient Product to Bundle!"))
            bundle.picking_out_id.action_done()
            valuation = sum(
                m.product_qty * m.price_unit for m in bundle.picking_out_id.move_lines) / bundle.product_uom_qty

            bundle.picking_in_id = self.env['stock.picking'].create({
                'picking_type_id': bundle.warehouse_id.in_type_id.id,
                'origin': bundle.name,
                'move_type': 'direct',
                'location_id': transit_location.id,
                'location_dest_id': bundle.warehouse_id.in_type_id.default_location_dest_id.id or False,
                'company_id': bundle.warehouse_id.company_id.id,
                'move_lines': [(0, 0, {
                    'product_id': bundle.product_id.id,
                    'product_uom': bundle.uom_id.id,
                    'price_unit': abs(valuation),
                    'name': str(bundle.product_id.display_name),
                    'product_uom_qty': bundle.product_uom_qty,
                    'quantity_done': bundle.product_uom_qty,
                    'company_id': bundle.warehouse_id.company_id.id,
                })]
            })
            bundle.picking_in_id.action_confirm()
            bundle.picking_in_id.with_context(
                force_valuation_amount=valuation * bundle.product_uom_qty).action_done()

    @api.multi
    def action_cancel(self):
        self.write({'state': 'cancel'})

    @api.multi
    def action_draft(self):
        self.write({'state': 'draft'})


class StockBundleLine(models.Model):
    _name = 'stock.bundle.line'
    _description = 'Bundle Product Line'

    bundle_id = fields.Many2one('stock.bundle', 'Bundle', ondelete="cascade")
    product_id = fields.Many2one('product.product', 'Product', required=True)
    uom_id = fields.Many2one('uom.uom', 'UoM', required=True)
    product_uom_qty = fields.Float('Qty', required=True)

    @api.onchange('product_id')
    def onchange_product(self):
        self.uom_id = self.product_id.uom_id.id
