# -*- coding: utf-8 -*-

import logging
from odoo import http, fields, _
from odoo.http import request
from odoo.exceptions import ValidationError, AccessError

_logger = logging.getLogger(__name__)


class LPRKioskController(http.Controller):
    """
    Отделен контролер за LPR Kiosk режим
    Само HTTP routes за киоск интерфейса
    """

    @http.route('/lpr_camera/kiosk', type='http', auth='user', website=True)
    def kiosk_mode(self, **kwargs):
        """Основен киоск режим"""
        try:
            self._validate_kiosk_access()

            # Намираме активна камера
            camera = request.env['lpr.camera.config'].search([
                ('active', '=', True)
            ], limit=1)

            if not camera:
                # Създаваме demo камера ако няма
                camera = self._create_demo_camera()

            values = {
                'camera': camera,
                'page_title': f'LPR Kiosk - {camera.name}',
                'kiosk_mode': True,
                'user': request.env.user,
                'company': request.env.company,
            }

            return request.render('lpr_camera_control.kiosk_fullscreen_template', values)

        except AccessError as e:
            return request.render('web.http_error', {
                'status_code': 403,
                'status_message': str(e)
            })
        except Exception as e:
            _logger.error(f"Грешка в kiosk_mode: {e}")
            return request.render('web.http_error', {
                'status_code': 500,
                'status_message': 'Грешка при зареждане на киоск режима'
            })

    @http.route('/lpr_camera/kiosk/<int:camera_id>', type='http', auth='user', website=True)
    def kiosk_mode_camera(self, camera_id, **kwargs):
        """Киоск режим за конкретна камера"""
        try:
            self._validate_kiosk_access()

            camera = request.env['lpr.camera.config'].browse(camera_id)

            if not camera.exists():
                return request.not_found()

            if not camera.active:
                return request.render('web.http_error', {
                    'status_code': 404,
                    'status_message': 'Камерата не е активна'
                })

            values = {
                'camera': camera,
                'page_title': f'LPR Kiosk - {camera.name}',
                'kiosk_mode': True,
                'user': request.env.user,
                'company': request.env.company,
            }

            return request.render('lpr_camera_control.kiosk_fullscreen_template', values)

        except AccessError as e:
            return request.render('web.http_error', {
                'status_code': 403,
                'status_message': str(e)
            })
        except Exception as e:
            _logger.error(f"Грешка в kiosk_mode_camera: {e}")
            return request.not_found()

    @http.route('/lpr_camera/kiosk/list', type='http', auth='user', website=True)
    def kiosk_camera_list(self, **kwargs):
        """Списък с налични камери за киоск режим"""
        try:
            self._validate_kiosk_access()

            cameras = request.env['lpr.camera.config'].search([
                ('active', '=', True)
            ])

            values = {
                'cameras': cameras,
                'page_title': 'Избор на камера за киоск режим',
                'user': request.env.user,
                'company': request.env.company,
            }

            return request.render('lpr_camera_control.kiosk_camera_list_template', values)

        except AccessError as e:
            return request.render('web.http_error', {
                'status_code': 403,
                'status_message': str(e)
            })
        except Exception as e:
            _logger.error(f"Грешка в kiosk_camera_list: {e}")
            return request.render('web.http_error', {
                'status_code': 500,
                'status_message': 'Грешка при зареждане на списъка с камери'
            })

    @http.route('/lpr_camera/kiosk/exit', type='http', auth='user', website=True)
    def kiosk_exit(self, **kwargs):
        """Излизане от киоск режим"""
        try:
            # Пренасочване към главната страница
            return request.redirect('/web')
        except Exception as e:
            _logger.error(f"Грешка при излизане от киоск: {e}")
            return request.redirect('/web')

    @http.route('/lpr_camera/kiosk/status', type='http', auth='user', website=False)
    def kiosk_status(self, **kwargs):
        """Статус на киоск режима"""
        try:
            # Проверяваме статуса на системата
            camera_count = request.env['lpr.camera.config'].search_count([
                ('active', '=', True)
            ])

            last_event = request.env['lpr.event'].search(
                [], limit=1, order='create_date desc'
            )

            # env няма атрибут bus_bus — проверява се дали модулът е зареден
            bus_available = 'bus.bus' in request.env

            status_info = {
                'kiosk_ready': camera_count > 0 and bus_available,
                'camera_count': camera_count,
                'bus_available': bus_available,
                'last_event_time': last_event.create_date.strftime('%Y-%m-%d %H:%M:%S') if last_event else None,
                'system_time': fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            return request.make_response(
                f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>LPR Kiosk Status</title>
                    <meta charset="utf-8">
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 40px; }}
                        .status {{ padding: 20px; border: 1px solid #ddd; border-radius: 8px; }}
                        .ready {{ background: #d4edda; border-color: #c3e6cb; }}
                        .not-ready {{ background: #f8d7da; border-color: #f5c6cb; }}
                        .info {{ margin: 10px 0; }}
                    </style>
                </head>
                <body>
                    <h1>🚗 LPR Kiosk Status</h1>
                    <div class="status {'ready' if status_info['kiosk_ready'] else 'not-ready'}">
                        <h2>{'✅ Системата е готова' if status_info['kiosk_ready'] else '❌ Системата не е готова'}</h2>
                        <div class="info"><strong>Активни камери:</strong> {status_info['camera_count']}</div>
                        <div class="info"><strong>Bus система:</strong> {'✅ Активна' if status_info['bus_available'] else '❌ Неактивна'}</div>
                        <div class="info"><strong>Последно събитие:</strong> {status_info['last_event_time'] or 'Няма'}</div>
                        <div class="info"><strong>Системно време:</strong> {status_info['system_time']}</div>
                    </div>
                    <p><a href="/lpr_camera/kiosk">🚀 Старт на киоск режим</a></p>
                    <p><a href="/web">🏠 Главно меню</a></p>
                </body>
                </html>
                """,
                headers=[('Content-Type', 'text/html')]
            )

        except Exception as e:
            _logger.error(f"Грешка в kiosk_status: {e}")
            return request.make_response(
                f"Грешка при проверка на статус: {str(e)}",
                status=500
            )

    # ==================== BUS TEST PANEL ====================
    # Тези маршрути обслужват тестовия панел на киоска. Каналът е твърдо
    # зададен тук — клиентът не може да избира по кой канал се излъчва.

    BUS_CHANNEL = 'lpr_camera_control'

    def _push(self, event_type, payload):
        """Излъчва по общия канал на модула"""
        request.env['bus.bus']._sendone(self.BUS_CHANNEL, event_type, payload)

    @http.route('/lpr_camera/bus_status', type='json', auth='user')
    def bus_status(self):
        """Дали bus модулът е наличен"""
        return {
            'status': 'success',
            'bus_active': 'bus.bus' in request.env,
            'channel': self.BUS_CHANNEL,
        }

    @http.route('/lpr_camera/test_bus', type='json', auth='user')
    def test_bus(self):
        """Изпраща тестово съобщение по шината"""
        try:
            self._push('lpr_test_event', {
                'message': _('Test notification from the LPR kiosk'),
                'timestamp': fields.Datetime.now().isoformat(),
                'user': request.env.user.name,
            })
            return {'status': 'success'}
        except Exception as e:
            _logger.warning(f"test_bus се провали: {e}")
            return {'status': 'error', 'message': str(e)}

    @http.route('/lpr_camera/send_bus_notification', type='json', auth='user')
    def send_bus_notification(self, event_type=None, event_data=None, **kwargs):
        """Излъчва произволен тип събитие с подадените данни"""
        if not event_type:
            return {'status': 'error', 'message': _('Missing event type')}
        try:
            self._push(event_type, event_data or {})
            return {'status': 'success'}
        except Exception as e:
            _logger.warning(f"send_bus_notification се провали: {e}")
            return {'status': 'error', 'message': str(e)}

    @http.route('/lpr_camera/trigger_lpr_event', type='json', auth='user')
    def trigger_lpr_event(self, plate_number=None, camera_name=None, **kwargs):
        """Симулира засечен номер"""
        try:
            event_data = {
                'plate': plate_number or 'TEST123',
                'camera_name': camera_name or _('Test Camera'),
                'timestamp': fields.Datetime.now().isoformat(),
                'confidence': 0.95,
                'image_path': None,
            }
            self._push('lpr_event_detected', event_data)
            return {'status': 'success', 'event_data': event_data}
        except Exception as e:
            _logger.warning(f"trigger_lpr_event се провали: {e}")
            return {'status': 'error', 'message': str(e)}

    @http.route('/lpr_camera/trigger_access_result', type='json', auth='user')
    def trigger_access_result(self, plate_number=None, access_granted=True, **kwargs):
        """Симулира решение за достъп"""
        try:
            granted = bool(access_granted)
            access_data = {
                'plate': plate_number or 'TEST123',
                'access_granted': granted,
                'access_reason': _('Simulated from the test panel'),
                'owner_name': request.env.user.name,
                'access_type': 'employee',
                'camera_name': _('Test Camera'),
            }
            self._push('lpr_access_result', access_data)
            return {'status': 'success', 'access_data': access_data}
        except Exception as e:
            _logger.warning(f"trigger_access_result се провали: {e}")
            return {'status': 'error', 'message': str(e)}

    @http.route('/lpr_camera/broadcast', type='json', auth='user')
    def broadcast(self, message=None, message_type='info', **kwargs):
        """Разпраща съобщение до всички слушащи клиенти"""
        try:
            self._push('lpr_broadcast', {
                'message': message or '',
                'message_type': message_type,
                'sender': request.env.user.name,
                'timestamp': fields.Datetime.now().isoformat(),
            })
            return {'status': 'success'}
        except Exception as e:
            _logger.warning(f"broadcast се провали: {e}")
            return {'status': 'error', 'message': str(e)}

    # ==================== HELPER METHODS ====================

    def _create_demo_camera(self):
        """Създава demo камера за тестване"""
        try:
            camera = request.env['lpr.camera.config'].create({
                'name': 'Demo Kiosk Camera',
                'ip_address': '192.168.1.100',
                'location': 'Главен вход - Kiosk режим',
                'active': True,
                'camera_type': 'lpr',
                'kiosk_mode': True,
            })
            _logger.info(f"Създадена demo камера за киоск: {camera.name}")
            return camera
        except Exception as e:
            _logger.error(f"Грешка при създаване на demo камера: {e}")
            raise ValidationError(_('Не може да се създаде demo камера за киоск режим'))

    def _validate_kiosk_access(self):
        """Проверява дали потребителят има достъп до киоск режима"""
        try:
            user = request.env.user

            # Проверяваме основни права
            if not user.has_group('base.group_user'):
                raise AccessError(_('Нямате права за достъп до киоск режима'))

            # Проверяваме дали потребителят е активен
            if not user.active:
                raise AccessError(_('Потребителският ви акаунт е неактивен'))

            # Допълнителни проверки ако са необходими
            # if not user.has_group('lpr_camera_control.group_lpr_user'):
            #     raise AccessError(_('Нямате права за LPR система'))

            return True

        except AccessError:
            raise
        except Exception as e:
            _logger.error(f"Грешка при валидация на kiosk достъп: {e}")
            raise AccessError(_('Грешка при проверка на права за достъп'))