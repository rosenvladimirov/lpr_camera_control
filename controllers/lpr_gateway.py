# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.http import request
import json
import logging
import hashlib
import os
from datetime import datetime

_logger = logging.getLogger(__name__)


class LprCataway(http.Controller):

    @http.route(['/lpr_gateway', '/lpr_gateway/<path:subpath>', '/'],
                type='http', auth='none', methods=['POST', 'GET'], csrf=False)
    def receive_camera_event(self, subpath='', **kwargs):
        """Приема POST/GET заявки от LPR камерите с Digest Authentication"""

        client_ip = request.httprequest.environ.get('REMOTE_ADDR', 'unknown')
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        method = request.httprequest.method
        path = request.httprequest.path

        _logger.info(f"🔍 {method} ЗАЯВКА от IP: {client_ip}, Path: {path}")
        _logger.info(f"📅 Време: {current_time}")

        # Проверяваме за Digest Authentication
        auth_header = request.httprequest.headers.get("Authorization")
        if auth_header and not self._verify_digest_auth(auth_header, method, path):
            return self._digest_auth_challenge()

        if method == 'GET':
            return self._handle_get_request(client_ip, current_time)
        else:  # POST
            return self._handle_post_request(client_ip, current_time, subpath)

    def _verify_digest_auth(self, auth_header, method, uri):
        """Проверява Digest Authentication"""
        try:
            env = request.env(user=1)

            # Вземаме настройките от камерата в базата данни
            camera = self._find_camera_by_ip(request.httprequest.environ.get('REMOTE_ADDR'))

            if camera:
                username = camera.gateway_username or 'admin'
                # Използваме хешираната парола или създаваме хеш от default паролата
                password_hash = camera.get_gateway_password()
                # За Digest auth трябва plain text паролата, така че използваме fallback
                password = 'admin'  # Default парола за Digest auth
                realm = camera.gateway_realm or 'RS realm'
                debug_mode = camera.gateway_debug or False
            else:
                # Fallback стойности ако няма камера в базата
                username = 'admin'
                password = 'admin'
                realm = 'RS realm'
                debug_mode = True

            # В DEBUG режим позволяваме всичко
            if debug_mode:
                _logger.info("🔧 DEBUG режим - пропускаме автентикация")
                return True

            if not auth_header.startswith("Digest "):
                return False

            # Парсираме Digest header
            auth_data = self._parse_authorization_header(auth_header)

            # Проверяваме digest
            ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
            ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
            expected_response = hashlib.md5(f"{ha1}:{auth_data.get('nonce', '')}:{ha2}".encode()).hexdigest()

            is_valid = expected_response == auth_data.get("response")
            _logger.info(f"🔐 Digest auth {'успешен' if is_valid else 'неуспешен'}")
            return is_valid

        except Exception as e:
            _logger.error(f"❌ Грешка при проверка на auth: {str(e)}")
            return False

    @staticmethod
    def _parse_authorization_header(header):
        """Парсира Digest Authorization header"""
        auth_data = {}
        if header.startswith("Digest "):
            values = header[7:].split(", ")
            for value in values:
                if "=" in value:
                    key, val = value.split("=", 1)
                    auth_data[key] = val.strip('"')
        return auth_data

    def _digest_auth_challenge(self):
        """Връща Digest Authentication challenge"""
        nonce = hashlib.md5(os.urandom(16)).hexdigest()
        realm = 'RS realm'

        challenge = f'Digest realm="{realm}", nonce="{nonce}"'

        return request.make_response(
            'Authorization Required',
            status=401,
            headers=[('WWW-Authenticate', challenge)]
        )

    def _handle_get_request(self, client_ip, current_time):
        """Обработва GET заявки"""
        camera_name = self._determine_camera_name(client_ip)

        _logger.info(f"🔍 GET ЗАЯВКА от {camera_name} ({client_ip})")

        response = f"LPR Gateway is running. Time: {current_time}"
        return request.make_response(
            response,
            headers=[('Content-Type', 'text/html')]
        )

    def _handle_post_request(self, client_ip, current_time, subpath):
        """Обработва POST заявки с LPR данни"""
        camera_name = self._determine_camera_name(client_ip)

        _logger.info(f"🔍 POST ЗАЯВКА от {camera_name} ({client_ip})")

        # Показваме важните headers за debug
        important_headers = ['Content-Type', 'Content-Length', 'Authorization', 'User-Agent']
        _logger.info("📋 ВАЖНИ HEADERS:")
        for header in important_headers:
            value = request.httprequest.headers.get(header)
            if value:
                if header == 'Authorization':
                    # Не показваме целия auth header в лога
                    _logger.info(f"   {header}: Digest (скрит за сигурност)")
                else:
                    _logger.info(f"   {header}: {value}")

        try:
            # Четем POST данните
            post_data = request.httprequest.get_data()
            content_length = len(post_data)

            _logger.info(f"📦 POST данни получени: {content_length} bytes")

            if content_length > 1000:
                _logger.info(f"📦 POST данни: {content_length} bytes (твърде големи за показване)")
            else:
                _logger.info(f"📦 RAW DATA: {post_data.decode('utf-8', errors='ignore')[:500]}...")

            # Парсираме JSON данните
            if post_data:
                try:
                    data = json.loads(post_data.decode('utf-8'))
                    _logger.info("📄 JSON данни успешно парсирани")

                    # Филтрираме големите данни за логиране
                    filtered_data = self._filter_large_data(data)
                    _logger.info(f"📄 PARSED JSON (селективно филтрирано):")
                    _logger.info(json.dumps(filtered_data, indent=2, ensure_ascii=False))

                    # Извличаме информация за номера
                    plate_info = self._extract_plate_info(data, client_ip)

                    if plate_info['plate_number']:
                        _logger.info("=" * 80)
                        _logger.info(f"🚗 ЗАСЕЧЕН РЕГИСТРАЦИОНЕН НОМЕР")
                        _logger.info(f"📅 Дата и час: {current_time}")
                        _logger.info(f"🔢 Номер: {plate_info['plate_number']}")
                        _logger.info(f"📍 Камера: {plate_info['camera_name']}")
                        _logger.info(f"🌐 IP адрес: {plate_info['client_ip']}")
                        _logger.info(f"⚙️ Устройство: {plate_info['device_name']}")
                        if plate_info['event_time'] and plate_info['event_time'] != current_time:
                            _logger.info(f"⏰ Време от камерата: {plate_info['event_time']}")
                        _logger.info("=" * 80)

                        # Създаваме LPR събитието в Odoo с контрол на достъпа
                        success, access_info = self._create_lpr_event(plate_info, data)

                        if success:
                            _logger.info("✅ LPR събитие създадено успешно")
                            if access_info.get('access_granted'):
                                _logger.info(f"🟢 ДОСТЪП РАЗРЕШЕН: {access_info.get('access_reason', 'N/A')}")
                            else:
                                _logger.warning(f"🔴 ДОСТЪП ОТКАЗАН: {access_info.get('access_reason', 'N/A')}")
                        else:
                            _logger.warning("⚠️ Проблем при създаване на LPR събитие")
                    else:
                        _logger.info(f"⚠️ Не е намерен регистрационен номер в данните от {camera_name}")

                except json.JSONDecodeError as e:
                    _logger.warning(f"❌ JSON декодиране неуспешно: {str(e)}")
                    # Все пак логваме raw данните
                    self._log_raw_event(client_ip, post_data.decode('utf-8', errors='ignore'))

            else:
                _logger.info("⚠️ Няма POST данни")

            # Винаги връщаме успешен отговор
            return self._success_response()

        except Exception as e:
            _logger.error(f"❌ Обща грешка при обработка на камера събитие: {str(e)}")
            return self._success_response()  # Все пак връщаме OK

    def _find_camera_by_ip(self, ip_address):
        """Намира камера по IP адрес"""
        try:
            env = request.env(user=1)
            camera = env['lpr.camera.config'].search([
                ('ip_address', '=', ip_address)
            ], limit=1)
            return camera
        except Exception as e:
            _logger.error(f"Грешка при търсене на камера по IP: {str(e)}")
            return None

    def _determine_camera_name(self, ip_address):
        """Определя името на камерата по IP"""
        try:
            camera = self._find_camera_by_ip(ip_address)

            if camera:
                return f"{camera.name} ({camera.full_address or 'Неизвестно местоположение'})"

            return f"Неизвестна камера ({ip_address})"

        except Exception as e:
            _logger.error(f"Грешка при определяне на името на камерата: {str(e)}")
            return f"Неизвестна камера ({ip_address})"

    def _filter_large_data(self, obj, max_length=100):
        """Филтриране на големи данни за логиране"""
        FILTERED_FIELDS = ['PlateImg', 'SnapImg', 'Image', 'Img', 'Picture', 'Photo', 'Binary', 'Data', 'Base64',
                           'ImageData']

        if isinstance(obj, dict):
            filtered = {}
            for key, value in obj.items():
                if any(field.lower() == key.lower() for field in FILTERED_FIELDS):
                    if isinstance(value, str) and len(value) > max_length:
                        filtered[key] = f"<ФИЛТРИРАНО: {len(value)} символа>"
                    elif isinstance(value, (list, dict)):
                        filtered[key] = f"<ФИЛТРИРАНО: {type(value).__name__} с данни>"
                    else:
                        filtered[key] = f"<ФИЛТРИРАНО: {type(value).__name__}>"
                else:
                    filtered[key] = self._filter_large_data(value, max_length)
            return filtered
        elif isinstance(obj, list):
            return [self._filter_large_data(item, max_length) for item in obj]
        elif isinstance(obj, str) and len(obj) > max_length * 20:
            return f"<ДЪЛЪГ СТРИНГ: {len(obj)} символа>"
        else:
            return obj

    def _extract_plate_info(self, data, client_ip):
        """Извлича информацията за номера"""
        plate_number = None
        event_time = None
        device_name = "Unknown"
        camera_name = self._determine_camera_name(client_ip)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if data:
            # Вариант 1: ai_snap_picture.PlateInfo
            plate_info_list = data.get("data", {}).get("ai_snap_picture", {}).get("PlateInfo", [])
            if isinstance(plate_info_list, list) and len(plate_info_list) > 0:
                plate = plate_info_list[0]
                plate_number = plate.get("SnapId")
                event_time = self._format_time(plate.get("StartTime"))
                _logger.info(f"✅ Намерен номер в ai_snap_picture.PlateInfo: {plate_number}")

            # Вариант 2: Директно в data
            elif "plate" in data:
                plate_number = data.get("plate")
                event_time = data.get("time", current_time)
                _logger.info(f"✅ Намерен номер директно в data: {plate_number}")

            # Вариант 3: Рекурсивно търсене
            else:
                _logger.info("🔍 Търсене на номер в цялата структура...")
                plate_number = self._find_plate_recursive(data)
                if plate_number:
                    _logger.info(f"✅ Намерен номер в структурата: {plate_number}")

            # Извличане на device info
            dev_info = data.get("data", {}).get("dev_net_info", [])
            if isinstance(dev_info, list) and len(dev_info) > 0:
                device_name = dev_info[0].get("device_name", dev_info[0].get("device", "Unknown"))
                _logger.info(f"📱 Device info: {device_name} на {client_ip}")

        return {
            'plate_number': plate_number,
            'event_time': event_time,
            'device_name': device_name,
            'camera_name': camera_name,
            'client_ip': client_ip
        }

    def _find_plate_recursive(self, obj, path=""):
        """Рекурсивно търсене на номер в структурата"""
        FILTERED_FIELDS = ['PlateImg', 'SnapImg', 'Image', 'Img', 'Picture', 'Photo', 'Binary', 'Data', 'Base64',
                           'ImageData']

        if isinstance(obj, dict):
            for key, value in obj.items():
                if any(field.lower() == key.lower() for field in FILTERED_FIELDS):
                    continue

                new_path = f"{path}.{key}" if path else key
                if key.lower() in ['plate', 'snapid', 'licenseplate', 'number', 'plateno', 'licenseno']:
                    _logger.info(f"🎯 Възможен номер в {new_path}: {value}")
                    return value
                result = self._find_plate_recursive(value, new_path)
                if result:
                    return result
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                result = self._find_plate_recursive(item, f"{path}[{i}]")
                if result:
                    return result
        return None

    def _format_time(self, value):
        """Форматиrane на времето от камерата"""
        try:
            timestamp = int(value)
            if timestamp > 1e10:  # Ако е в милисекунди
                timestamp = timestamp // 1000
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except:
            return str(value) if value else None

    def _create_lpr_event(self, plate_info, raw_data):
        """Създава LPR събитие в Odoo с контрол на достъпа и излиза в bus шината"""
        try:
            env = request.env(user=1)  # Използваме SUPERUSER

            # Намираме или създаваме камера
            camera = env['lpr.camera.config'].search([
                ('ip_address', '=', plate_info['client_ip'])
            ], limit=1)

            if not camera:
                # Създаваме нова камера ако не съществува
                camera = env['lpr.camera.config'].create({
                    'name': plate_info['camera_name'],
                    'ip_address': plate_info['client_ip'],
                    'location_description': plate_info['camera_name'],
                    'active': True,
                })
                _logger.info(f"📷 Създадена нова камера: {camera.name}")

            # Обновяваме последното виждане на камерата
            camera.update_last_seen()

            # Създаваме LPR събитието
            event_vals = {
                'plate_number': plate_info['plate_number'],
                'camera_id': camera.id,
                'event_time': datetime.now(),
                'device_name': plate_info['device_name'],
                'raw_data': json.dumps(raw_data, ensure_ascii=False, indent=2),
            }

            if plate_info['event_time']:
                try:
                    if isinstance(plate_info['event_time'], str):
                        event_vals['camera_time'] = datetime.strptime(plate_info['event_time'], "%Y-%m-%d %H:%M:%S")
                    else:
                        event_vals['camera_time'] = plate_info['event_time']
                except:
                    pass  # Игнорираме грешки при парсиране на времето

            # Проверка за контрол на достъпа ПРЕДИ създаване на събитието
            access_info = self._check_plate_access(env, plate_info['plate_number'], camera.id)

            # Добавяме информацията за достъпа към събитието
            event_vals.update({
                'access_granted': access_info['access_granted'],
                'access_reason': access_info['access_reason'],
                'processing_status': 'processed' if access_info['access_granted'] else 'access_denied',
                'processed': True,
            })

            # Ако има регистриран автомобил, добавяме връзките
            if access_info.get('car_registry'):
                car_registry = access_info['car_registry']
                event_vals['car_registry_id'] = car_registry.id
                if car_registry.employee_id:
                    event_vals['employee_id'] = car_registry.employee_id.id
                elif car_registry.partner_id:
                    event_vals['partner_id'] = car_registry.partner_id.id

            # Създаваме събитието
            event = env['lpr.event'].create(event_vals)

            # Изпращаме bus уведомления за real-time updates
            self._send_lpr_bus_notifications(env, event, access_info)

            # Ако достъпът е разрешен и има служител, създаваме attendance
            if access_info['access_granted'] and event.employee_id:
                self._create_attendance_from_event(env, event, event.employee_id)

            # Логваме резултата
            self._log_access_result(event, access_info)

            # Commit промените
            env.cr.commit()

            _logger.info(f"✅ LPR събитие създадено: ID {event.id}")
            return True, access_info

        except Exception as e:
            _logger.error(f"❌ Грешка при създаване на LPR събитие: {str(e)}")
            return False, {'access_granted': False, 'access_reason': f'Системна грешка: {str(e)}'}

    def _send_lpr_bus_notifications(self, env, event, access_info):
        """Изпраща bus уведомления за LPR событията"""
        try:
            # Изпращаме LPR събитие засечено
            self._send_bus_notification(env, 'lpr_event_detected', {
                'plate': event.plate_number,
                'camera_name': event.camera_id.name,
                'timestamp': event.event_time.isoformat() if event.event_time else None,
                'confidence': 0.95,
                'image_path': None,
            })

            # Изпращаме резултат от достъпа
            self._send_bus_notification(env, 'lpr_access_result', {
                'event_id': event.id,
                'plate': event.plate_number,
                'access_granted': access_info['access_granted'],
                'access_reason': access_info['access_reason'],
                'owner_name': event.employee_id.name if event.employee_id else (
                    event.partner_id.name if event.partner_id else None
                ),
                'access_type': access_info['car_registry'].access_type if access_info.get('car_registry') else None,
                'event_time': event.event_time.isoformat() if event.event_time else None,
                'processing_status': event.processing_status,
                'camera_name': event.camera_id.name,
            })

            _logger.info("📤 Bus уведомления изпратени успешно")

        except Exception as e:
            _logger.error(f"❌ Грешка при изпращане на bus уведомления: {str(e)}")

    def _send_bus_notification(self, env, event_type, event_data, channel='lpr_camera_control'):
        """Изпраща bus уведомление"""
        try:
            env['bus.bus']._sendone(channel, event_type, event_data)
            _logger.debug(f"🚌 Bus уведомление изпратено: {event_type}")
        except Exception as e:
            _logger.warning(f"Не успя да изпрати bus уведомление: {str(e)}")

    def _check_plate_access(self, env, plate_number, camera_id):
        """Проверява достъпа за дадена кола"""
        try:
            # Търсене в регистъра на автомобили
            car_registry = env['car.registry'].find_by_plate(plate_number)

            if not car_registry:
                # Неизвестен автомобил
                return {
                    'access_granted': False,
                    'access_reason': "Неизвестен автомобил - не е регистриран в системата",
                    'car_registry': None
                }

            # Ако има повече от един запис, вземаме първия активен
            car_registry = car_registry[0]

            # Проверка на достъпа
            access_allowed, reason = car_registry.check_access(camera_id)

            return {
                'access_granted': access_allowed,
                'access_reason': reason,
                'car_registry': car_registry
            }

        except Exception as e:
            return {
                'access_granted': False,
                'access_reason': f'Грешка при проверка на достъпа: {str(e)}',
                'car_registry': None
            }

    def _create_attendance_from_event(self, env, event, employee):
        """Създава attendance запис от LPR събитие"""
        try:
            # Проверяваме последния attendance
            last_attendance = env['hr.attendance'].search([
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
                attendance = env['hr.attendance'].create(attendance_vals)
                event.attendance_id = attendance.id
                _logger.info(f"⏰ Attendance check_in създаден за {employee.name}")

                # Изпращаме bus уведомение за attendance
                self._send_bus_notification(env, 'lpr_attendance_created', {
                    'employee_name': employee.name,
                    'check_type': 'check_in',
                    'check_time': event.event_time.isoformat() if event.event_time else None,
                    'plate': event.plate_number,
                    'camera_name': event.camera_id.name
                })
            else:
                last_attendance.check_out = event.event_time
                event.attendance_id = last_attendance.id
                _logger.info(f"⏰ Attendance check_out създаден за {employee.name}")

                # Изпращаме bus уведомение за attendance
                self._send_bus_notification(env, 'lpr_attendance_created', {
                    'employee_name': employee.name,
                    'check_type': 'check_out',
                    'check_time': event.event_time.isoformat() if event.event_time else None,
                    'plate': event.plate_number,
                    'camera_name': event.camera_id.name
                })

        except Exception as e:
            _logger.error(f"❌ Грешка при създаване на attendance: {str(e)}")
            event.processing_status = 'error'
            event.error_message = f"Attendance error: {str(e)}"

            # Изпращаме bus уведомение за грешка
            try:
                self._send_bus_notification(env, 'lpr_error', {
                    'error': f"Attendance error: {str(e)}",
                    'plate': event.plate_number,
                    'camera_name': event.camera_id.name,
                    'timestamp': datetime.now().isoformat(),
                    'error_code': 'ATTENDANCE_ERROR'
                })
            except:
                pass

    def _log_access_result(self, event, access_info):
        """Логва резултата от проверката на достъпа"""
        try:
            env = request.env(user=1)

            if access_info['access_granted']:
                # Разрешен достъп
                owner_info = "Неизвестен"
                if event.employee_id:
                    owner_info = f"Служител: {event.employee_id.name}"
                elif event.partner_id:
                    owner_info = f"Партньор: {event.partner_id.name}"

                message = f"✅ ДОСТЪП РАЗРЕШЕН\n" \
                          f"Номер: {event.plate_number}\n" \
                          f"Собственик: {owner_info}\n" \
                          f"Камера: {event.camera_id.name}\n" \
                          f"Време: {event.event_time}\n" \
                          f"Причина: {access_info['access_reason']}"

                level = 'INFO'
                log_name = 'LPR Access Granted'

            else:
                # Отказан достъп
                message = f"❌ ДОСТЪП ОТКАЗАН\n" \
                          f"Номер: {event.plate_number}\n" \
                          f"Камера: {event.camera_id.name}\n" \
                          f"Време: {event.event_time}\n" \
                          f"Причина: {access_info['access_reason']}"

                level = 'WARNING'
                log_name = 'LPR Access Denied'

            env['ir.logging'].create({
                'name': log_name,
                'type': 'server',
                'level': level,
                'message': message,
                'func': '_log_access_result',
                'path': 'lpr_camera_control.controllers.camera_stream',
            })

        except Exception as e:
            _logger.error(f"❌ Грешка при логване на резултат: {str(e)}")

    def _log_raw_event(self, client_ip, raw_data):
        """Логва raw събитие което не е JSON"""
        try:
            env = request.env(user=1)
            env['ir.logging'].create({
                'name': f'LPR Raw Event from {client_ip}',
                'type': 'server',
                'level': 'INFO',
                'message': f"Raw data: {raw_data[:1000]}...",
                'func': 'receive_camera_event',
                'path': 'lpr_camera_control.controllers.camera_stream',
            })
            env.cr.commit()
        except Exception as e:
            _logger.error(f"❌ Грешка при логване на raw събитие: {str(e)}")

    def _success_response(self):
        """Връща успешен отговор"""
        return request.make_response(
            json.dumps({"status": "ok", "message": "Data received"}).encode("utf-8"),
            headers=[('Content-Type', 'application/json')]
        )

    # =============== API ENDPOINTS ===============

    @http.route('/lpr_camera/access_check/<string:plate_number>', type='json', auth='user', methods=['GET'])
    def check_plate_access_api(self, plate_number, camera_id=None):
        """API за проверка на достъпа на номер"""
        try:
            env = request.env
            camera_id = int(camera_id) if camera_id else None

            access_info = self._check_plate_access(env, plate_number, camera_id)

            return {
                'status': 'success',
                'access_granted': access_info['access_granted'],
                'access_reason': access_info['access_reason'],
                'car_info': {
                    'owner': access_info['car_registry'].owner_name if access_info['car_registry'] else None,
                    'access_type': access_info['car_registry'].access_type if access_info['car_registry'] else None,
                } if access_info['car_registry'] else None
            }

        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }

    @http.route('/lpr_camera/recent_events', type='json', auth='user', methods=['GET'])
    def get_recent_events(self, limit=20, since=None):
        """Връща последните LPR събития"""
        try:
            domain = []
            if since:
                # Филтриране по време ако е подаден since параметър
                try:
                    since_date = datetime.fromisoformat(since.replace('Z', '+00:00'))
                    domain.append(('create_date', '>', since_date))
                except ValueError:
                    pass  # Игнорираме грешни дати

            events = request.env['lpr.event'].search(
                domain,
                order='create_date desc',
                limit=int(limit)
            )

            result = []
            for event in events:
                result.append({
                    'id': event.id,
                    'plate_number': event.plate_number,
                    'camera_name': event.camera_id.name,
                    'event_time': event.event_time.isoformat() if event.event_time else None,
                    'access_granted': event.access_granted,
                    'access_reason': event.access_reason,
                    'owner_name': event.employee_id.name if event.employee_id else (
                        event.partner_id.name if event.partner_id else None
                    ),
                    'processing_status': event.processing_status,
                })

            return {
                'status': 'success',
                'events': result
            }

        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }

    @http.route('/lpr_camera/config', type='json', auth='user', methods=['GET'])
    def get_camera_config(self):
        """Връща конфигурация на камерите за frontend"""
        try:
            cameras = request.env['lpr.camera.config'].search([('active', '=', True)])
            result = []

            for camera in cameras:
                camera_info = {
                    'id': camera.id,
                    'name': camera.name,
                    'ip_address': camera.ip_address,
                    'location': camera.full_address or camera.location_description,
                    'connection_status': camera.connection_status,
                    'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
                }

                result.append(camera_info)

            return {
                'status': 'success',
                'cameras': result
            }

        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }