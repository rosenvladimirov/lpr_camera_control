# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime


class ParkingSession(models.Model):
    _name = 'parking.session'
    _description = 'Parking Session for Partners/Visitors'
    _order = 'start_time desc'

    name = fields.Char('Session Name', compute='_compute_name', store=True)
    partner_id = fields.Many2one('res.partner', string='Partner/Visitor', required=True)
    car_registry_id = fields.Many2one('car.registry', string='Vehicle')
    plate_number = fields.Char('Plate Number', required=True, index=True)

    # Времена
    start_time = fields.Datetime('Entry Time', required=True, default=fields.Datetime.now)
    end_time = fields.Datetime('Exit Time')
    duration = fields.Float('Duration (Hours)', compute='_compute_duration', store=True)
    duration_text = fields.Char('Duration Text', compute='_compute_duration_text', store=True)

    # LPR събития
    entry_event_id = fields.Many2one('lpr.event', string='Entry LPR Event')
    exit_event_id = fields.Many2one('lpr.event', string='Exit LPR Event')
    entry_camera_id = fields.Many2one('lpr.camera.config', string='Entry Camera')
    exit_camera_id = fields.Many2one('lpr.camera.config', string='Exit Camera')

    # Статус
    state = fields.Selection([
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='active', index=True)

    # Допълнителни полета
    notes = fields.Text('Notes')
    location_zone = fields.Char('Parking Zone')

    @api.depends('plate_number', 'partner_id')
    def _compute_name(self):
        for record in self:
            partner_name = record.partner_id.name if record.partner_id else 'Unknown'
            record.name = f"{record.plate_number} - {partner_name}"

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for record in self:
            if record.start_time and record.end_time:
                delta = record.end_time - record.start_time
                record.duration = delta.total_seconds() / 3600.0  # В часове
            elif record.start_time and not record.end_time:
                # Ако все още е активна сесията, изчисляваме текущата продължителност
                delta = datetime.now() - record.start_time
                record.duration = delta.total_seconds() / 3600.0
            else:
                record.duration = 0.0

    @api.depends('duration')
    def _compute_duration_text(self):
        for record in self:
            if record.duration:
                hours = int(record.duration)
                minutes = int((record.duration - hours) * 60)
                record.duration_text = f"{hours}ч {minutes:02d}мин"
            else:
                record.duration_text = "0ч 00мин"

    def action_complete_session(self):
        """Завършва паркинг сесията"""
        self.ensure_one()
        if self.state == 'active':
            self.write({
                'state': 'completed',
                'end_time': fields.Datetime.now()
            })
        return True

    def get_duration_for_payment(self):
        """Връща информацията за престоя за плащане"""
        self.ensure_one()

        if self.state == 'active':
            # Ако сесията е още активна, изчисляваме текущия престой
            current_time = datetime.now()
            delta = current_time - self.start_time
            current_duration = delta.total_seconds() / 3600.0
        else:
            current_duration = self.duration

        hours = int(current_duration)
        minutes = int((current_duration - hours) * 60)

        return {
            'session_id': self.id,
            'partner_name': self.partner_id.name,
            'plate_number': self.plate_number,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_hours': current_duration,
            'duration_text': f"{hours}ч {minutes:02d}мин",
            'location_zone': self.location_zone,
            'state': self.state,
            'is_active': self.state == 'active'
        }

    def get_current_duration(self):
        """Връща текущия престой в часове (за активни сесии)"""
        self.ensure_one()
        if self.state == 'active' and self.start_time:
            delta = datetime.now() - self.start_time
            return delta.total_seconds() / 3600.0
        return self.duration or 0.0

    @api.model
    def get_active_sessions(self):
        """Връща всички активни паркинг сесии"""
        sessions = self.search([('state', '=', 'active')])
        result = []

        for session in sessions:
            result.append(session.get_duration_for_payment())

        return result

    @api.model
    def find_active_session_by_plate(self, plate_number):
        """Намира активна сесия по номер на кола"""
        return self.search([
            ('plate_number', '=', plate_number),
            ('state', '=', 'active')
        ], limit=1)

    def action_view_payment_info(self):
        """Action за показване на информация за плащане"""
        payment_info = self.get_duration_for_payment()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'Паркинг информация за {self.plate_number}',
                'message': f"Партньор: {payment_info['partner_name']}\n"
                           f"Влизане: {payment_info['start_time'].strftime('%H:%M %d.%m.%Y')}\n"
                           f"{'Излизане: ' + payment_info['end_time'].strftime('%H:%M %d.%m.%Y') if payment_info['end_time'] else 'Активна сесия'}\n"
                           f"Престой: {payment_info['duration_text']}\n"
                           f"Зона: {payment_info['location_zone'] or 'N/A'}",
                'type': 'info',
                'sticky': True
            }
        }