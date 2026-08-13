# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api
import json


class LprEvent(models.Model):
    _name = 'lpr.event'
    _description = 'LPR Camera Event'
    # Формата носи чатър — без миксина валидацията на изгледа пада при инсталация
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char('Event Name', compute='_compute_name', store=True)
    plate_number = fields.Char('Plate Number', required=True, index=True)
    plate_number_normalized = fields.Char('Normalized Plate', compute='_compute_normalized_plate', store=True,
                                          index=True)
    camera_id = fields.Many2one('lpr.camera.config', string='Camera', required=True)
    event_time = fields.Datetime('Event Time', required=True, default=fields.Datetime.now)
    camera_time = fields.Datetime('Camera Time')

    # Данни от камерата
    device_name = fields.Char('Device Name')
    raw_data = fields.Text('Raw Data')

    # Връзка с регистъра на автомобили
    car_registry_id = fields.Many2one('car.registry', string='Registered Car')

    # Връзка с attendance
    attendance_id = fields.Many2one('hr.attendance', string='Related Attendance')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    partner_id = fields.Many2one('res.partner', string='Partner/Visitor')

    # Връзка с паркинг сесия
    parking_session_id = fields.Many2one('parking.session', string='Related Parking Session')

    # Контрол на достъпа
    access_granted = fields.Boolean('Access Granted', default=False, index=True)
    access_reason = fields.Char('Access Reason')

    # Статус на събитието
    processed = fields.Boolean('Processed', default=False)
    processing_status = fields.Selection([
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('access_denied', 'Access Denied'),
        ('error', 'Error'),
        ('ignored', 'Ignored')
    ], string='Status', default='pending', index=True)

    error_message = fields.Text('Error Message')

    @api.depends('plate_number', 'camera_id')
    def _compute_name(self):
        for record in self:
            if record.plate_number and record.camera_id:
                record.name = f"{record.plate_number} - {record.camera_id.name}"
            else:
                record.name = record.plate_number or "Unknown"

    @api.depends('plate_number')
    def _compute_normalized_plate(self):
        for record in self:
            record.plate_number_normalized = self.env['car.registry']._normalize_license_plate(record.plate_number)

    @api.model
    def create_from_mqtt(self, mqtt_data):
        """Създава LPR събитие от MQTT данни с контрол на достъпа"""
        try:
            if isinstance(mqtt_data, str):
                data = json.loads(mqtt_data)
            else:
                data = mqtt_data

            # Намиране на камерата по IP
            camera = self.env['lpr.camera.config'].search([
                ('ip_address', '=', data.get('ip'))
            ], limit=1)

            if not camera:
                # Създаване на нова камера ако не съществува
                camera = self.env['lpr.camera.config'].create({
                    'name': data.get('camera_name', f"Camera {data.get('ip')}"),
                    'ip_address': data.get('ip'),
                    'location_description': data.get('camera_name', ''),
                })

            # Създаване на събитието
            event = self.create({
                'plate_number': data.get('plate'),
                'camera_id': camera.id,
                'event_time': fields.Datetime.now(),
                'camera_time': data.get('camera_time'),
                'device_name': data.get('device'),
                'raw_data': json.dumps(data, ensure_ascii=False, indent=2),
            })

            # Проверка за достъп
            self._check_and_process_access(event)

            return event

        except Exception as e:
            self.env['ir.logging'].create({
                'name': 'LPR Event Creation Error',
                'type': 'server',
                'level': 'ERROR',
                'message': f"Error creating LPR event: {str(e)}\nData: {mqtt_data}",
                'func': 'create_from_mqtt',
                'path': 'lpr_camera_control.models.lpr_event',
            })
            return False

    def _check_and_process_access(self, event):
        """Проверява достъпа и обработва събитието"""
        try:
            # Търсене в регистъра на автомобили
            car_registry = self.env['car.registry'].find_by_plate(event.plate_number)

            if not car_registry:
                # Неизвестен автомобил
                event.access_granted = False
                event.access_reason = "Неизвестен автомобил - не е регистриран в системата"
                event.processing_status = 'access_denied'
                self._log_access_denied(event, "Неизвестен автомобил")
                return

            # Ако има повече от един запис, вземаме първия активен
            car_registry = car_registry[0]
            event.car_registry_id = car_registry.id

            # Проверка на достъпа
            access_allowed, reason = car_registry.check_access(event.camera_id.id)

            if access_allowed:
                # Достъпът е разрешен
                event.access_granted = True
                event.access_reason = reason
                event.processing_status = 'processed'

                # Свързваме със служител или партньор
                if car_registry.employee_id:
                    event.employee_id = car_registry.employee_id.id
                    self._create_attendance_from_event(event, car_registry.employee_id)
                elif car_registry.partner_id:
                    event.partner_id = car_registry.partner_id.id
                    # НОВА ФУНКЦИОНАЛНОСТ: Обработка на паркинг сесии за партньори
                    self._handle_partner_parking(event, car_registry)

                self._log_access_granted(event, car_registry)

            else:
                # Достъпът е отказан
                event.access_granted = False
                event.access_reason = reason
                event.processing_status = 'access_denied'

                if car_registry.employee_id:
                    event.employee_id = car_registry.employee_id.id
                elif car_registry.partner_id:
                    event.partner_id = car_registry.partner_id.id

                self._log_access_denied(event, reason)

            event.processed = True

        except Exception as e:
            event.processing_status = 'error'
            event.error_message = str(e)
            event.access_granted = False
            event.access_reason = f"Грешка при проверка: {str(e)}"

    def _create_attendance_from_event(self, event, employee):
        """Създава attendance запис от LPR събитие"""
        try:
            # Логика за определяне на check_in/check_out
            last_attendance = self.env['hr.attendance'].search([
                ('employee_id', '=', employee.id)
            ], order='create_date desc', limit=1)

            check_in = not last_attendance or last_attendance.check_out

            attendance_vals = {
                'employee_id': employee.id,
                'lpr_event_id': event.id,
                'created_by_lpr': True,
            }

            if check_in:
                attendance_vals['check_in'] = event.event_time
                attendance = self.env['hr.attendance'].create(attendance_vals)
                event.attendance_id = attendance.id
            else:
                last_attendance.check_out = event.event_time
                event.attendance_id = last_attendance.id

        except Exception as e:
            event.processing_status = 'error'
            event.error_message = f"Attendance error: {str(e)}"

    def _handle_partner_parking(self, event, car_registry):
        """Обработва паркинг сесии за партньори/посетители"""
        try:
            # Търсим активна паркинг сесия за този номер
            active_session = self.env['parking.session'].find_active_session_by_plate(event.plate_number)

            if active_session:
                # Exit - завършваме сесията
                active_session.write({
                    'end_time': event.event_time,
                    'exit_event_id': event.id,
                    'exit_camera_id': event.camera_id.id,
                    'state': 'completed'
                })
                event.parking_session_id = active_session.id

                self._log_parking_exit(event, active_session)
                self._send_parking_notification(active_session, 'exit')

            else:
                # Entry - започваме нова сесия
                parking_session = self.env['parking.session'].create({
                    'partner_id': car_registry.partner_id.id,
                    'car_registry_id': car_registry.id,
                    'plate_number': event.plate_number,
                    'start_time': event.event_time,
                    'entry_event_id': event.id,
                    'entry_camera_id': event.camera_id.id,
                    'location_zone': event.camera_id.location_description,
                    'state': 'active'
                })
                event.parking_session_id = parking_session.id

                self._log_parking_entry(event, parking_session)
                self._send_parking_notification(parking_session, 'entry')

        except Exception as e:
            self.env['ir.logging'].create({
                'name': 'Parking Session Error',
                'type': 'server',
                'level': 'ERROR',
                'message': f"Error handling parking session: {str(e)}",
                'func': '_handle_partner_parking',
                'path': 'lpr_camera_control.models.lpr_event',
            })

    def _log_parking_entry(self, event, parking_session):
        """Логва влизане в паркинга"""
        self.env['ir.logging'].create({
            'name': 'Parking Entry',
            'type': 'server',
            'level': 'INFO',
            'message': f"🅿️ ПАРКИНГ ВЛИЗАНЕ\n"
                       f"Номер: {event.plate_number}\n"
                       f"Партньор: {parking_session.partner_id.name}\n"
                       f"Камера: {event.camera_id.name}\n"
                       f"Време: {event.event_time}\n"
                       f"Зона: {parking_session.location_zone}",
            'func': '_log_parking_entry',
            'path': 'lpr_camera_control.models.lpr_event',
        })

    def _log_parking_exit(self, event, parking_session):
        """Логва излизане от паркинга"""
        duration_info = parking_session.get_duration_for_payment()

        self.env['ir.logging'].create({
            'name': 'Parking Exit',
            'type': 'server',
            'level': 'INFO',
            'message': f"🅿️ ПАРКИНГ ИЗЛИЗАНЕ\n"
                       f"Номер: {event.plate_number}\n"
                       f"Партньор: {parking_session.partner_id.name}\n"
                       f"Престой: {duration_info['duration_text']}\n"
                       f"Зона: {parking_session.location_zone}\n"
                       f"Време: {event.event_time}",
            'func': '_log_parking_exit',
            'path': 'lpr_camera_control.models.lpr_event',
        })

    def _send_parking_notification(self, parking_session, event_type):
        """Изпраща bus уведомление за паркинг събитие"""
        try:
            notification_data = {
                'session_id': parking_session.id,
                'partner_name': parking_session.partner_id.name,
                'plate_number': parking_session.plate_number,
                'duration': parking_session.duration,
                'duration_text': parking_session.duration_text,
                'location_zone': parking_session.location_zone,
                'event_type': event_type,
                'timestamp': fields.Datetime.now().isoformat(),
                'state': parking_session.state
            }

            if hasattr(self.env, 'bus_bus'):
                self.env['bus.bus']._sendone(
                    'lpr_camera_control',
                    {
                        'type': 'parking_event',
                        'data': notification_data
                    }
                )
        except Exception as e:
            # Не спираме процеса ако bus уведомлението не успее
            pass

    def _log_access_granted(self, event, car_registry):
        """Логва разрешен достъп"""
        owner_info = car_registry.employee_id.name if car_registry.employee_id else (
            car_registry.partner_id.name if car_registry.partner_id else 'Неизвестен'
        )

        # Определяваме типа на достъпа
        access_type = "Служител" if car_registry.employee_id else (
            "Партньор/Посетител" if car_registry.partner_id else "Непознат"
        )

        self.env['ir.logging'].create({
            'name': f'LPR Access Granted',
            'type': 'server',
            'level': 'INFO',
            'message': f"✅ ДОСТЪП РАЗРЕШЕН\n"
                       f"Номер: {event.plate_number}\n"
                       f"Собственик: {owner_info}\n"
                       f"Тип: {access_type}\n"
                       f"Камера: {event.camera_id.name}\n"
                       f"Време: {event.event_time}\n"
                       f"Причина: {event.access_reason}",
            'func': '_log_access_granted',
            'path': 'lpr_camera_control.models.lpr_event',
        })

    def _log_access_denied(self, event, reason):
        """Логва отказан достъп"""
        self.env['ir.logging'].create({
            'name': f'LPR Access Denied',
            'type': 'server',
            'level': 'WARNING',
            'message': f"❌ ДОСТЪП ОТКАЗАН\n"
                       f"Номер: {event.plate_number}\n"
                       f"Камера: {event.camera_id.name}\n"
                       f"Време: {event.event_time}\n"
                       f"Причина: {reason}",
            'func': '_log_access_denied',
            'path': 'lpr_camera_control.models.lpr_event',
        })

    def action_view_parking_session(self):
        """Action за преглед на свързаната паркинг сесия"""
        if self.parking_session_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'parking.session',
                'res_id': self.parking_session_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Няма паркинг сесия',
                'message': 'Това LPR събитие няма свързана паркинг сесия.',
                'type': 'warning',
                'sticky': False
            }
        }

    def get_event_summary(self):
        """Връща обобщена информация за събитието"""
        self.ensure_one()

        summary = {
            'id': self.id,
            'plate_number': self.plate_number,
            'event_time': self.event_time,
            'camera_name': self.camera_id.name,
            'access_granted': self.access_granted,
            'access_reason': self.access_reason,
            'processing_status': self.processing_status,
            'event_type': None,
            'related_record': None
        }

        if self.employee_id:
            summary.update({
                'event_type': 'attendance',
                'related_record': {
                    'model': 'hr.employee',
                    'id': self.employee_id.id,
                    'name': self.employee_id.name
                }
            })
        elif self.parking_session_id:
            summary.update({
                'event_type': 'parking',
                'related_record': {
                    'model': 'parking.session',
                    'id': self.parking_session_id.id,
                    'name': self.parking_session_id.name,
                    'duration': self.parking_session_id.duration_text,
                    'state': self.parking_session_id.state
                }
            })
        elif self.partner_id:
            summary.update({
                'event_type': 'visitor',
                'related_record': {
                    'model': 'res.partner',
                    'id': self.partner_id.id,
                    'name': self.partner_id.name
                }
            })

        return summary
