from odoo import models, fields


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    lpr_event_id = fields.Many2one('lpr.event', string='LPR Event')
    created_by_lpr = fields.Boolean('Created by LPR', default=False)
    plate_number = fields.Char('Plate Number', related='lpr_event_id.plate_number', store=True)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Премахваме старото поле car_plate
    car_registrations = fields.One2many('car.registry', 'employee_id', string='Car Registrations')
    car_registrations_count = fields.Integer('Cars Count', compute='_compute_car_registrations_count')
    lpr_events_count = fields.Integer('LPR Events', compute='_compute_lpr_events_count')

    def _compute_car_registrations_count(self):
        for employee in self:
            employee.car_registrations_count = len(employee.car_registrations)

    def _compute_lpr_events_count(self):
        for employee in self:
            employee.lpr_events_count = self.env['lpr.event'].search_count([
                ('employee_id', '=', employee.id)
            ])


class ResPartner(models.Model):
    _inherit = 'res.partner'

    car_registrations = fields.One2many('car.registry', 'partner_id', string='Car Registrations')
    car_registrations_count = fields.Integer('Cars Count', compute='_compute_car_registrations_count')
    lpr_events_count = fields.Integer('LPR Events', compute='_compute_lpr_events_count')

    def _compute_car_registrations_count(self):
        for partner in self:
            partner.car_registrations_count = len(partner.car_registrations)

    def _compute_lpr_events_count(self):
        for partner in self:
            partner.lpr_events_count = self.env['lpr.event'].search_count([
                ('partner_id', '=', partner.id)
            ])