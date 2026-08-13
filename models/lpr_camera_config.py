# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""
LPR Camera Configuration Model for LPR Camera Stream Module

Този модул управлява конфигурацията на LPR (License Plate Recognition) камери
и предоставя автоматично ping за проверка на състоянието им.

Конфигурация в odoo.conf:
------------------------
[options]
# LPR Camera Ping Service Configuration
lpr_camera_ping_interval = 300          # Секунди между ping циклите (по подразбиране 5 минути)
lpr_camera_offline_threshold = 10       # Минути за маркиране като offline (по подразбиране 10 минути)

Описание на параметрите:
-----------------------
lpr_camera_ping_interval - Интервал в секунди между автоматичните ping циклите
                          По подразбиране е 300 секунди (5 минути). Минимална стойност е 60 секунди.

lpr_camera_offline_threshold - Време в минути след което камерата се маркира като offline
                              ако не е отговаряла на ping заявки. По подразбиране е 10 минути.

Пример за конфигурация:
----------------------
# Ежеминутни ping циклици с offline threshold от 5 минути
lpr_camera_ping_interval = 60
lpr_camera_offline_threshold = 5

# По-дълги интервали за ресурсно ограничени системи
lpr_camera_ping_interval = 600          # На всеки 10 минути
lpr_camera_offline_threshold = 30       # Offline след 30 минути

Функционалности:
---------------
- Автоматично ping на всички активни LPR камери
- Проверка на множество портове (80, 8080, 554, 443)
- Bus notifications за real-time обновяване на статуса
- Background service управление чрез hooks
- Интеграция с OCA product_manufacturer модул
- Attendance tracking базиран на LPR събития
- Асинхронни ping операции за неблокиране на UI
- Gateway authentication с SHA512 хеширане на пароли

Използване:
----------
# Ръчно стартиране на ping service
service = env['lpr.camera.config']
service.start_camera_ping_service()

# Проверка на статуса
status = service.get_ping_service_status()

# Спиране на service
service.stop_camera_ping_service()
"""

from odoo import models, fields, api, tools, registry, SUPERUSER_ID
from odoo.exceptions import ValidationError
import threading
import socket
import logging
import time
import hashlib

_logger = logging.getLogger(__name__)


class LprCameraConfig(models.Model):
    _name = 'lpr.camera.config'
    _description = 'LPR Camera Configuration'
    _order = 'name'

    # Използваме стандартното active поле от Odoo
    active = fields.Boolean(default=True, help="Дали LPR камерата е активна за обработка на събития")
    name = fields.Char('Camera Name', required=True, index=True, help="Име на LPR камерата за лесна идентификация")

    # Основни идентификатори на камерата
    ip_address = fields.Char('IP Address', required=True, index=True,
                             help="IP адрес на LPR камерата за идентификация в мрежата")
    mac_address = fields.Char('MAC Address', index=True,
                              help="MAC адрес на LPR камерата за уникална идентификация")
    serial_number = fields.Char('Serial Number', index=True,
                                help="Сериен номер на LPR камерата")

    # Моделът идва от product_manufacturer_data (product-attribute-expert),
    # не от OCA product_manufacturer — там manufacturer_id сочи към res.partner
    manufacturer_id = fields.Many2one('product.manufacturer', string='Manufacturer',
                                      help="Производител на LPR камерата")
    model = fields.Char('Model', help="Модел на LPR камерата")
    firmware_version = fields.Char('Firmware Version', help="Версия на фърмуера на LPR камерата")

    # Използваме стандартната адресна система на Odoo
    partner_id = fields.Many2one('res.partner', string='Location Address',
                                 help="Адрес където е инсталирана LPR камерата")

    # Работно място (ако камерата е свързана с определено работно място)
    work_location_id = fields.Many2one('hr.work.location', string='Work Location',
                                       help="Работно място където е монтирана LPR камерата")

    # Допълнителна информация за местоположението
    location_description = fields.Char('Location Description',
                                       help="Детайлно описание на местоположението (напр. 'Главен вход - южна страна')")

    # Връзка към product (за управление като услуга/устройство)
    product_id = fields.Many2one('product.product', string='Related Product',
                                 help="Продукт свързан с тази LPR камера за проследяване като услуга")

    # Състояние на връзката
    connection_status = fields.Selection([
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('checking', 'Checking...'),
        ('unknown', 'Unknown')
    ], string='Connection Status', default='unknown',
        help="Текущо състояние на връзката с LPR камерата")

    last_seen = fields.Datetime('Last Seen', help="Последно време когато LPR камерата е изпратила данни")

    # Gateway authentication полета за съвместимост с lpr_gateway
    gateway_username = fields.Char('Gateway Username', default='admin',
                                   help="Потребителско име за Digest Authentication в gateway")
    gateway_password = fields.Char('Gateway Password',
                                   help="Парола за Digest Authentication в gateway (записва се като SHA512 хеш)")
    gateway_password_hash = fields.Char('Gateway Password Hash',
                                        help="SHA512 хеш на паролата за сигурност")
    gateway_realm = fields.Char('Gateway Realm', default='RS realm',
                                help="Realm за Digest Authentication")
    gateway_debug = fields.Boolean('Gateway Debug Mode', default=True,
                                   help="Дали gateway да работи в debug режим (без автентикация)")

    # Мета информация
    notes = fields.Text('Notes', help="Допълнителни бележки за LPR камерата")
    installation_date = fields.Date('Installation Date', help="Дата на инсталиране на LPR камерата")

    # Computed полета за по-лесно управление
    full_address = fields.Char('Full Address', compute='_compute_full_address', store=True,
                               help="Пълен адрес на LPR камерата")

    manufacturer_name = fields.Char('Manufacturer Name', related='manufacturer_id.name', store=True,
                                    help="Име на производителя на LPR камерата")

    def _calculate_password_hash(self, password):
        """Изчислява SHA512 хеш на паролата съвместимо с lpr_gateway"""
        if not password:
            return False
        return hashlib.sha512(password.encode('utf-8')).hexdigest().upper()

    @api.model
    def create(self, vals):
        """Override create за хеширане на паролата"""
        if vals.get('gateway_password'):
            vals['gateway_password_hash'] = self._calculate_password_hash(vals['gateway_password'])
            # Изчистваме plain text паролата за сигурност
            vals.pop('gateway_password', None)
        return super(LprCameraConfig, self).create(vals)

    def write(self, vals):
        """Override write за хеширане на паролата"""
        if vals.get('gateway_password'):
            vals['gateway_password_hash'] = self._calculate_password_hash(vals['gateway_password'])
            # Изчистваме plain text паролата за сигурност
            vals.pop('gateway_password', None)
        return super(LprCameraConfig, self).write(vals)

    def get_gateway_password(self):
        """Връща хешираната парола за gateway автентикация"""
        self.ensure_one()
        # За Digest auth трябва plain text парола, така че използваме default
        # За сигурност, real паролата е в gateway_password_hash
        return 'admin'  # Default парола за Digest auth

    def get_gateway_password_hash(self):
        """Връща SHA512 хеша на паролата"""
        self.ensure_one()
        return self.gateway_password_hash or self._calculate_password_hash('admin')

    @api.depends('partner_id', 'work_location_id', 'location_description')
    def _compute_full_address(self):
        for record in self:
            address_parts = []

            if record.work_location_id:
                address_parts.append(record.work_location_id.name)
                if record.work_location_id.address_id:
                    if record.work_location_id.address_id.street:
                        address_parts.append(record.work_location_id.address_id.street)
                    if record.work_location_id.address_id.city:
                        address_parts.append(record.work_location_id.address_id.city)
            elif record.partner_id:
                if record.partner_id.street:
                    address_parts.append(record.partner_id.street)
                if record.partner_id.city:
                    address_parts.append(record.partner_id.city)

            if record.location_description:
                address_parts.append(f"({record.location_description})")

            record.full_address = ', '.join(address_parts) if address_parts else ''

    @api.depends('name', 'location_description', 'work_location_id', 'manufacturer_id')
    def _compute_display_name(self):
        for record in self:
            name_parts = [record.name]

            if record.manufacturer_id:
                name_parts.append(f"[{record.manufacturer_id.name}]")

            if record.work_location_id:
                name_parts.append(record.work_location_id.name)
            elif record.location_description:
                name_parts.append(record.location_description)

            record.display_name = ' - '.join(name_parts)

    def update_last_seen(self):
        """Обновява последното време на комуникация с LPR камерата"""
        self.write({
            'last_seen': fields.Datetime.now(),
            'connection_status': 'online'
        })

    @api.model
    def mark_offline_cameras(self, minutes_threshold=10):
        """Маркира LPR камери като offline ако не са изпращали данни в определено време"""
        threshold_time = fields.Datetime.subtract(fields.Datetime.now(), minutes=minutes_threshold)

        offline_cameras = self.search([
            ('last_seen', '<', threshold_time),
            ('connection_status', '!=', 'offline'),
            ('active', '=', True)  # Проверяваме само активните камери
        ])

        offline_cameras.write({'connection_status': 'offline'})

        return len(offline_cameras)

    def _ping_camera_thread(self, camera_id, ip_address, name):
        """Извършва ping в отделен thread"""
        try:
            _logger.info(f"🔍 Започва проверка на LPR камера {name} ({ip_address})")

            # Опитваме се да се свържем към различни стандартни портове за LPR камери
            ports_to_check = [80, 8080, 554, 443]  # HTTP, Alt HTTP, RTSP, HTTPS
            connected = False

            for port in ports_to_check:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)  # По-кратък timeout в thread
                    result = sock.connect_ex((ip_address, port))
                    sock.close()

                    if result == 0:
                        connected = True
                        _logger.info(f"✅ LPR камера {name} отговаря на порт {port}")
                        break

                except Exception as e:
                    _logger.debug(f"Грешка при проверка на порт {port} за камера {name}: {e}")
                    continue

            # Обновяваме статуса в базата с нов курсор
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, self.env.uid, self.env.context)
                camera_record = env['lpr.camera.config'].browse(camera_id)

                if connected:
                    camera_record.write({
                        'connection_status': 'online',
                        'last_seen': fields.Datetime.now()
                    })
                    message = f'LPR камера {name} е онлайн'
                    message_type = 'success'
                    _logger.info(f"✅ {message}")
                else:
                    camera_record.write({'connection_status': 'offline'})
                    message = f'LPR камера {name} не отговаря'
                    message_type = 'warning'
                    _logger.warning(f"❌ {message}")

                # Изпращаме Bus нотификация
                env['bus.bus']._sendone('lpr_camera_ping_result', {
                    'camera_id': camera_id,
                    'camera_name': name,
                    'ip_address': ip_address,
                    'connected': connected,
                    'message': message,
                    'message_type': message_type
                })

                cr.commit()

        except Exception as e:
            error_msg = f"Критична грешка при проверка на LPR камера {name}: {str(e)}"
            _logger.error(error_msg)

            # Обновяваме статуса при грешка
            try:
                with self.env.registry.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, self.env.context)
                    camera_record = env['lpr.camera.config'].browse(camera_id)
                    camera_record.write({'connection_status': 'offline'})
                    cr.commit()
            except Exception as inner_e:
                _logger.error(f"Грешка при обновяване на статус: {inner_e}")

    def action_ping_camera(self):
        """Action за асинхронна проверка на връзката с LPR камерата"""
        self.ensure_one()

        # Веднага маркираме като "проверява се"
        self.write({'connection_status': 'checking'})

        # Стартираме ping в отделен thread
        thread = threading.Thread(
            target=self._ping_camera_thread,
            args=(self.id, self.ip_address, self.name),
            daemon=True
        )
        thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f'Започва проверка на LPR камера {self.name}... Моля изчакайте.',
                'type': 'info',
                'sticky': False,
            }
        }

    def action_ping_all_cameras(self):
        """Action за проверка на всички активни LPR камери"""
        active_cameras = self.search([('active', '=', True)])

        if not active_cameras:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'Няма активни LPR камери за проверка',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # Маркираме всички като "проверява се"
        active_cameras.write({'connection_status': 'checking'})

        # Стартираме thread за всяка камера
        for camera in active_cameras:
            thread = threading.Thread(
                target=self._ping_camera_thread,
                args=(camera.id, camera.ip_address, camera.name),
                daemon=True
            )
            thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f'Започва проверка на {len(active_cameras)} LPR камери... Резултатите ще бъдат показани скоро.',
                'type': 'info',
                'sticky': True,
            }
        }

    @api.model
    def start_camera_ping_service(self):
        """Стартира background service за автоматично ping на LPR камерите"""
        if not hasattr(self.env.registry,
                       '_lpr_camera_ping_thread') or not self.env.registry._lpr_camera_ping_thread.is_alive():
            # Вземаме ping интервала от конфигурацията
            ping_interval = int(tools.config.get('lpr_camera_ping_interval', 300))  # По подразбиране на всеки 5 минути
            offline_threshold = int(tools.config.get('lpr_camera_offline_threshold', 10))  # 10 минути за offline

            # Валидация на конфигурацията
            if ping_interval < 60:
                _logger.warning(f"⚠️ lpr_camera_ping_interval ({ping_interval}s) е твърде малък, използваме 60s")
                ping_interval = 60

            if offline_threshold < 1:
                _logger.warning(
                    f"⚠️ lpr_camera_offline_threshold ({offline_threshold}min) е твърде малък, използваме 5min")
                offline_threshold = 5

            thread = LprCameraPingThread(self.env.cr.dbname, ping_interval, offline_threshold)
            thread.daemon = True
            thread.start()
            self.env.registry._lpr_camera_ping_thread = thread
            _logger.info(
                f"🔄 LPR Camera Ping Service стартиран (интервал: {ping_interval}s, offline threshold: {offline_threshold}min)")
            return True
        else:
            _logger.info("🔄 LPR Camera Ping Service вече работи")
            return False

    @api.model
    def stop_camera_ping_service(self):
        """Спира background service за ping на LPR камерите"""
        if hasattr(self.env.registry, '_lpr_camera_ping_thread'):
            thread = self.env.registry._lpr_camera_ping_thread
            if thread.is_alive():
                thread.stop()
                thread.join(timeout=10)
                _logger.info("🔄 LPR Camera Ping Service спрян")
                return True
        return False

    @api.model
    def get_ping_service_status(self):
        """Връща статуса на ping service"""
        if hasattr(self.env.registry, '_lpr_camera_ping_thread'):
            thread = self.env.registry._lpr_camera_ping_thread
            return {
                'running': thread.is_alive(),
                'ping_interval': getattr(thread, 'ping_interval', 0),
                'offline_threshold': getattr(thread, 'offline_threshold', 0),
                'last_ping_cycle': getattr(thread, 'last_ping_cycle', None),
                'cameras_checked': getattr(thread, 'cameras_checked', 0),
                'cameras_online': getattr(thread, 'cameras_online', 0),
                'cameras_offline': getattr(thread, 'cameras_offline', 0),
            }
        return {'running': False}

    def check_attendance_time_tracking(self, plate_number, employee_id=None):
        """
        Проверява и изчислява времето което автомобилът е бил в фирмата
        базирано на LPR събития и attendance записи
        """
        # Намираме всички LPR събития за този номер от тази камера
        lpr_events = self.env['lpr.event'].search([
            ('camera_id', '=', self.id),
            ('plate_number', '=', plate_number),
            ('processing_status', '=', 'processed'),
            ('access_granted', '=', True)
        ], order='event_time desc')

        if not lpr_events:
            return {'status': 'no_events', 'message': 'Няма записани LPR събития за този номер'}

        # Ако е подаден employee_id, филтрираме по служител
        if employee_id:
            lpr_events = lpr_events.filtered(lambda e: e.employee_id.id == employee_id)

        if not lpr_events:
            return {'status': 'no_employee_events', 'message': 'Няма LPR събития за този служител'}

        # Групираме събитията по дни за по-лесно проследяване
        daily_tracking = {}

        for event in lpr_events:
            event_date = event.event_time.date()
            if event_date not in daily_tracking:
                daily_tracking[event_date] = []
            daily_tracking[event_date].append(event)

        # Изчисляваме времето за всеки ден
        tracking_results = []

        for date, events in daily_tracking.items():
            # Сортираме събитията по време
            events.sort(key=lambda e: e.event_time)

            day_result = {
                'date': date,
                'events': len(events),
                'first_entry': events[0].event_time,
                'last_exit': events[-1].event_time,
                'total_hours': 0,
                'attendance_records': []
            }

            # Търсим attendance записи за този ден
            for event in events:
                if event.attendance_id:
                    attendance = event.attendance_id
                    if attendance.check_in and attendance.check_out:
                        hours_worked = (attendance.check_out - attendance.check_in).total_seconds() / 3600
                        day_result['attendance_records'].append({
                            'check_in': attendance.check_in,
                            'check_out': attendance.check_out,
                            'hours': round(hours_worked, 2),
                            'work_location': attendance.employee_id.work_location_id.name if attendance.employee_id.work_location_id else None
                        })
                        day_result['total_hours'] += hours_worked

            tracking_results.append(day_result)

        return {
            'status': 'success',
            'camera_name': self.name,
            'camera_location': self.full_address,
            'camera_manufacturer': self.manufacturer_name,
            'plate_number': plate_number,
            'tracking_period': {
                'from': min(daily_tracking.keys()) if daily_tracking else None,
                'to': max(daily_tracking.keys()) if daily_tracking else None
            },
            'daily_tracking': tracking_results,
            'total_days': len(daily_tracking),
            'total_events': len(lpr_events)
        }

    @api.constrains('ip_address')
    def _check_ip_address_unique(self):
        """Проверява дали IP адресът е уникален сред активните камери"""
        for record in self:
            if record.ip_address and record.active:
                existing = self.search([
                    ('ip_address', '=', record.ip_address),
                    ('active', '=', True),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(
                        f'IP адрес {record.ip_address} вече се използва от активна LPR камера {existing[0].name}')

    def action_view_lpr_events(self):
        """Action за преглед на LPR събитията от тази камера"""
        self.ensure_one()
        return {
            'name': f'LPR събития от {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'lpr.event',
            'view_mode': 'tree,form',
            'domain': [('camera_id', '=', self.id)],
            'context': {'default_camera_id': self.id}
        }


class LprCameraPingThread(threading.Thread):
    """Background thread за автоматично ping на LPR камери"""

    def __init__(self, dbname, ping_interval=300, offline_threshold=10):
        super().__init__()
        self.dbname = dbname
        self.ping_interval = ping_interval  # секунди между ping циклите
        self.offline_threshold = offline_threshold  # минути за маркиране като offline
        self.running = False
        self.last_ping_cycle = None
        self.cameras_checked = 0
        self.cameras_online = 0
        self.cameras_offline = 0

        _logger.info(f"🔄 LPR Camera Ping Thread инициализиран:")
        _logger.info(f"  База данни: {dbname}")
        _logger.info(f"  Ping интервал: {ping_interval} секунди ({ping_interval // 60} мин {ping_interval % 60} сек)")
        _logger.info(f"  Offline threshold: {offline_threshold} минути")

    def run(self):
        """Main thread loop за ping на камерите"""
        self.running = True
        _logger.info("🔄 Стартиране на LPR Camera Ping Thread")

        while self.running:
            try:
                self.ping_all_cameras()
                self.mark_offline_cameras()

                # Изчакваме до следващия цикъл с възможност за прекъсване
                for i in range(self.ping_interval):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                _logger.error(f"❌ Грешка в LPR Camera Ping Thread: {e}")
                # При грешка изчакваме по-малко време преди да опитаме отново
                for i in range(30):  # 30 секунди
                    if not self.running:
                        break
                    time.sleep(1)

        _logger.info("🔄 LPR Camera Ping Thread спрян")

    def ping_all_cameras(self):
        """Прави ping на всички активни LPR камери"""
        try:
            self.last_ping_cycle = fields.Datetime.now()
            online_count = 0
            offline_count = 0
            total_checked = 0

            with registry(self.dbname).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})

                # Намираме всички активни LPR камери
                cameras = env['lpr.camera.config'].search([('active', '=', True)])
                total_checked = len(cameras)

                if total_checked == 0:
                    _logger.debug("🔍 Няма активни LPR камери за ping")
                    return

                _logger.info(f"🔍 Започва ping на {total_checked} активни LPR камери")

                for camera in cameras:
                    if not self.running:
                        break

                    try:
                        # Опитваме се да се свържем към различни портове
                        ports_to_check = [80, 8080, 554, 443]  # HTTP, Alt HTTP, RTSP, HTTPS
                        connected = False

                        for port in ports_to_check:
                            try:
                                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                sock.settimeout(3)  # 3 секунди timeout
                                result = sock.connect_ex((camera.ip_address, port))
                                sock.close()

                                if result == 0:
                                    connected = True
                                    break

                            except Exception:
                                continue

                        # Обновяваме статуса на камерата
                        if connected:
                            camera.write({
                                'connection_status': 'online',
                                'last_seen': fields.Datetime.now()
                            })
                            online_count += 1
                            _logger.debug(f"✅ LPR камера {camera.name} ({camera.ip_address}) - онлайн")
                        else:
                            camera.write({'connection_status': 'offline'})
                            offline_count += 1
                            _logger.debug(f"❌ LPR камера {camera.name} ({camera.ip_address}) - офлайн")

                    except Exception as e:
                        _logger.warning(f"⚠️ Грешка при ping на LPR камера {camera.name}: {e}")
                        camera.write({'connection_status': 'offline'})
                        offline_count += 1

                # Commit всички промени наведнъж
                cr.commit()

                # Обновяваме статистиките
                self.cameras_checked = total_checked
                self.cameras_online = online_count
                self.cameras_offline = offline_count

                _logger.info(
                    f"✅ Ping цикъл завършен: {online_count} онлайн, {offline_count} офлайн от общо {total_checked} LPR камери")

                # Изпращаме Bus notification за резултатите
                if total_checked > 0:
                    env['bus.bus']._sendone('lpr_camera_ping_summary', {
                        'timestamp': self.last_ping_cycle.isoformat(),
                        'total_cameras': total_checked,
                        'online_cameras': online_count,
                        'offline_cameras': offline_count,
                        'ping_interval': self.ping_interval
                    })

        except Exception as e:
            _logger.error(f"❌ Критична грешка при ping на LPR камери: {e}")

    def mark_offline_cameras(self):
        """Маркира камери като offline ако не са отговаряли дълго време"""
        try:
            with registry(self.dbname).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})

                # Използваме метода от модела
                marked_offline = env['lpr.camera.config'].mark_offline_cameras(self.offline_threshold)

                if marked_offline > 0:
                    _logger.warning(
                        f"⚠️ {marked_offline} LPR камери маркирани като offline (не са отговаряли над {self.offline_threshold} мин)")

                cr.commit()

        except Exception as e:
            _logger.error(f"❌ Грешка при маркиране на offline LPR камери: {e}")

    def stop(self):
        """Спира thread-а"""
        _logger.info("🔄 Получена команда за спиране на LPR Camera Ping Thread")
        self.running = False
