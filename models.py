from odoo import tools, models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date,datetime
from psycopg2 import sql

class ResPartner(models.Model):
    _inherit = 'res.partner'

    #@api.constrains('ref')
    #def check_ref_unique(self):
    #    if self.ref and self.ref != '':
    #        partners = self.env['res.partner'].search([('ref','=',self.ref)])
    #        if len(partners) > 1:
    #            raise ValidationError('Ya existen partners con codigo %s'%(self.ref))


    _sql_constraints = [
        ('ref_unique','UNIQUE(ref)','El campo referencia del partner debe ser unico'),
    ]


class StockPickingPurchase(models.Model):
    _name = 'stock.picking.purchase'
    _description = 'stock.picking.purchase'

    @api.onchange('purchase_order_id')
    def onchange_partner_id(self):
        if self.purchase_order_id:
            self.partner_id = self.purchase_order_id.partner_id.id

    picking_id = fields.Many2one('stock.picking','Transferencia')
    partner_id = fields.Many2one('res.partner',string='Proveedor')
    purchase_order_id = fields.Many2one('purchase.order','Orden de compra')
    product_id = fields.Many2one('product.product','Producto')
    qty = fields.Float('Cantidad')
    uom_id = fields.Many2one('uom.uom','Unidad de medida',store=True,compute="_compute_dest_qty")
    dest_uom_id = fields.Many2one('uom.uom','UoM destino',compute="_compute_dest_qty",store=True)
    dest_qty = fields.Float('Cantidad destino',compute="_compute_dest_qty",store=True)

    @api.depends('product_id','purchase_order_id','qty')
    def _compute_dest_qty(self):
        for rec in self:
            picking_id = rec.picking_id
            move_lines = picking_id.move_lines.filtered(lambda l: l.product_id.id == self.product_id.id)
            if move_lines:
                rec.uom_id = move_lines[0].product_uom.id
            if rec.product_id and rec.purchase_order_id and rec.uom_id and rec.qty:
                po_lines = self.env['purchase.order.line'].search(
                    [('product_id','=',rec.product_id.id),
                     ('order_id','=',rec.purchase_order_id.id)],
                    limit=1
                    )
                current_uom = rec.uom_id
                if rec.uom_id.id != po_lines.product_uom.id:
                    final_qty = current_uom._compute_quantity(rec.qty,po_lines.product_uom)
                else:
                    final_qty = rec.qty
                rec.dest_qty = final_qty
                rec.dest_uom_id = po_lines.product_uom.id
            else:
                rec.uom_id = None
                rec.dest_qty = 0
                rec.dest_uom_id = None


    @api.constrains('product_id','qty')
    def check_product_id(self):
        for rec in self:
            if rec.product_id and rec.purchase_order_id:
                po_lines = self.env['purchase.order.line'].search(
                    [('product_id','=',rec.product_id.id),
                     ('order_id','=',rec.purchase_order_id.id)],
                    limit=1
                    )
            if not po_lines:
                raise ValidationError('Producto %s no esta presente en el pedido'%(rec.product_id.name))
            picking_id = rec.picking_id
            move_lines = picking_id.move_lines.filtered(lambda l: l.product_id.id == rec.product_id.id)
            if move_lines:
                current_uom = move_lines[0].product_uom
            if current_uom.id != po_lines.product_uom.id:
                final_qty = current_uom._compute_quantity(rec.qty,po_lines.product_uom)
            else:
                final_qty = rec.qty
            if po_lines.product_qty < final_qty:
                raise ValidationError('La cantidad asignada no puede ser mayor a la cantidad pedida')
        products = {}
        lines = self.env['stock.picking.purchase'].search([('picking_id','=',self.picking_id.id)])
        for rec in lines:
            if rec.product_id.id not in products:
                products[rec.product_id.id] = rec.qty
            else:
                products[rec.product_id.id] = products[rec.product_id.id] + rec.qty 
        for key,val in products.items():
            move_line = self.env['stock.move'].search([
                ('picking_id','=',rec.picking_id.id),
                ('product_id','=',key)])
            if not move_line\
                    or move_line.quantity_done < val:
                product = self.env['product.product'].browse(key)
                raise ValidationError('Cantidades ingresadas para el producto %s incorrectas'%(product.name))


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    picking_purchase_ids = fields.One2many(comodel_name='stock.picking.purchase',inverse_name='picking_id',string='Ordenes de compra')

    def apply_picking_purchase_ids(self):
        self.ensure_one()
        purchases = {}
        # Recepciones por orden de compra
        for picking_purchase in self.picking_purchase_ids:
            if picking_purchase.purchase_order_id.id not in purchases:
                purchases[picking_purchase.purchase_order_id.id] = [picking_purchase.picking_id.id]
            else:
                if picking_purchase.picking_id.id not in purchases[picking_purchase.purchase_order_id.id]:
                    purchases[picking_purchase.purchase_order_id.id].append(picking_purchase.picking_id.id)
        for key, item in purchases.items():
            purchase = self.env['purchase.order'].browse(key)
            purchase.picking_ids = [(6,0,item)]
        # Cantidades por producto y orden de compra
        sql_select = sql.SQL(
            """
            select purchase_order_id,product_id,sum(dest_qty) as qty
            from stock_picking_purchase
            group by 1,2
            """
            )
        self._cr.execute(sql_select)
        res = self._cr.fetchall()
        for record in res:
            sql_update = sql.SQL(
                """
                    UPDATE purchase_order_line SET
                    qty_received = %s
                    WHERE order_id = %s
                    and product_id = %s
                    """
                )
            self._cr.execute(sql_update, (record[2], record[0], record[1]))


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def action_mark_done(self):
        self.ensure_one()
        if not self.done and self.state in ['done','purchase']:
            self.done = True

    picking_ids = fields.Many2many('stock.picking', string='Receptions', copy=False)
    done = fields.Boolean('Finalizada',copy=False)

