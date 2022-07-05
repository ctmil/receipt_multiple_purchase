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

    def onchange_partner_id(self):
        if self.purchase_order_id:
            self.partner_id = self.purchase_order_id.partner_id.id

    picking_id = fields.Many2one('stock.picking','Transferencia')
    partner_id = fields.Many2one('res.partner',string='Proveedor')
    purchase_order_id = fields.Many2one('purchase.order','Orden de compra')
    product_id = fields.Many2one('product.product','Producto')
    qty = fields.Integer('Cantidad')

    @api.constrains('product_id','qty')
    def check_product_id(self):
        if self.product_id and self.purchase_order_id:
            po_lines = self.env['purchase.order.line'].search(
                    [('product_id','=',self.product_id.id),
                     ('order_id','=',self.purchase_order_id.id)],
                    limit=1
                    )
            if not po_lines:
                raise ValidationError('Producto %s no esta presente en el pedido'%(self.product_id.name))
            if po_lines.product_qty < self.qty:
                raise ValidationError('La cantidad asignada no puede ser mayor a la cantidad pedida')

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
            select purchase_order_id,product_id,sum(qty) as qty
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

    picking_ids = fields.Many2many('stock.picking', string='Receptions', copy=False)


