import threading
import time
import logging
from datetime import datetime
import json
from odoo import api, fields, models, registry, SUPERUSER_ID
from odoo.tools import config

_logger = logging.getLogger(__name__)

# Опитваме се да импортираме ONVIF библиотеките
try:
    from zeep import Client
    from zeep.wsse.username import UsernameToken
    import requests
    from requests.auth import HTTPDigestAuth

    ONVIF_AVAILABLE = True
except ImportError as e:
    _logger.warning(f"ONVIF библиотеки не са налични: {e}")
    ONVIF_AVAILABLE = False


class ONVIFCameraService(models.TransientModel):
    _name = 'onvif.camera.service'
    _description = 'ONVIF Camera Service Background'

    @api.model
    def start_onvif_server(self):
        """Стартира ONVIF сървъра в отделен thread"""
        if not ONVIF_AVAILABLE:
            _logger.error("ONVIF библиотеки не са инсталирани. Инсталирайте: pip install zeep requests")
            return False

        if not hasattr(self.env.registry,
                       '_onvif_server_thread') or not self.env.registry._onvif_server_thread.is_alive():
            server = ONVIFCameraServer(self.env.cr.dbname)
            thread = threading.Thread(target=server.run_server, daemon=True)
            thread.start()

            self.env.registry._onvif_server_thread = thread
            self.env.registry._onvif_server_instance = server

            _logger.info("🚀 ONVIF Camera Server стартиран")
            return True
        else:
            _logger.info("ONVIF Server вече работи")
            return False

    @api.model
    def stop_onvif_server(self):
        """Спира ONVIF сървъра"""
        if hasattr(self.env.registry, '_onvif_server_instance'):
            server = self.env.registry._onvif_server_instance
            server.stop_server()

            thread = getattr(self.env.registry, '_onvif_server_thread', None)
            if thread and thread.is_alive():
                thread.join(timeout=5)

            _logger.info("🛑 ONVIF Camera Server спрян")
            return True
        return False

    @api.model
    def get_onvif_status(self):
        """Връща статуса на ONVIF сървъра"""
        if not ONVIF_AVAILABLE:
            return {
                'running': False,
                'error': 'ONVIF библиотеки не са инсталирани'
            }

        if hasattr(self.env.registry, '_onvif_server_instance'):
            server = self.env.registry._onvif_server_instance
            return server.get_server_status()

        return {'running': False}

    @api.model
    def sync_cameras_from_config(self):
        """Синхронизира камери от конфигурацията"""
        try:
            # Зареждаме ONVIF камери от lpr.camera.config
            cameras = self.env['lpr.camera.config'].search([
                ('camera_type', 'in', ['hikvision', 'dahua', 'onvif_generic']),
                ('is_active', '=', True)
            ])

            if hasattr(self.env.registry, '_onvif_server_instance'):
                server = self.env.registry._onvif_server_instance

                for camera in cameras:
                    camera_config = {
                        'ip': camera.ip_address,
                        'username': camera.onvif_username or 'admin',
                        'password': camera.onvif_password or '',
                        'port': camera.onvif_port or 80,
                        'type': camera.camera_type,
                        'barrier_name': camera.name,
                        'location': camera.location
                    }

                    server.add_camera(str(camera.id), camera_config)

                _logger.info(f"📷 Синхронизирани {len(cameras)} ONVIF камери")
                return True

        except Exception as e:
            _logger.error(f"❌ Грешка при синхронизация на камери: {e}")
            return False


class ONVIFCameraServer:
    """ONVIF Camera Server за управление на камери"""

    def __init__(self, dbname):
        self.dbname = dbname
        self.cameras = {}
        self.controllers = {}
        self.running = False
        self.monitor_interval = 30

    def add_camera(self, camera_id, camera_config):
        """Добавя камера към сървъра"""
        self.cameras[camera_id] = camera_config
        _logger.info(f"📷 Добавена ONVIF камера {camera_id}: {camera_config['ip']}")

    def run_server(self):
        """Главен loop на сървъра"""
        self.running = True
        _logger.info("🔄 ONVIF Server loop стартиран")

        while self.running:
            try:
                self._initialize_cameras()
                self._monitor_cameras()
                time.sleep(self.monitor_interval)

            except Exception as e:
                _logger.error(f"❌ Грешка в ONVIF server loop: {e}")
                time.sleep(5)

        _logger.info("🔄 ONVIF Server loop спрян")

    def stop_server(self):
        """Спира сървъра"""
        self.running = False

        for controller in self.controllers.values():
            controller.stop_monitoring()

    def _initialize_cameras(self):
        """Инициализира камери които не са свързани"""
        for camera_id, camera_config in self.cameras.items():
            if camera_id not in self.controllers:
                try:
                    controller = ONVIFBarrierController(
                        camera_ip=camera_config["ip"],
                        username=camera_config["username"],
                        password=camera_config["password"],
                        camera_type=camera_config.get("type", "onvif_generic"),
                        barrier_name=camera_config.get("barrier_name", f"Camera {camera_id}"),
                        camera_id=camera_id,
                        port=camera_config.get("port", 80),
                        dbname=self.dbname
                    )

                    if controller.connect():
                        controller.start_monitoring()
                        self.controllers[camera_id] = controller
                        _logger.info(f"✅ ONVIF камера {camera_id} свързана")
                    else:
                        _logger.warning(f"⚠️ Неуспешно свързване с ONVIF камера {camera_id}")

                except Exception as e:
                    _logger.error(f"❌ Грешка при ONVIF камера {camera_id}: {e}")

    def _monitor_cameras(self):
        """Мониторинг на свързаните камери"""
        disconnected_cameras = []

        for camera_id, controller in self.controllers.items():
            if not controller.is_connected():
                _logger.warning(f"📵 ONVIF камера {camera_id} е изключена")
                disconnected_cameras.append(camera_id)

        for camera_id in disconnected_cameras:
            controller = self.controllers.pop(camera_id, None)
            if controller:
                controller.stop_monitoring()

    def get_server_status(self):
        """Връща статуса на сървъра"""
        status = {
            'running': self.running,
            'cameras_configured': len(self.cameras),
            'cameras_connected': len(self.controllers),
            'cameras': {}
        }

        for camera_id in self.cameras:
            controller = self.controllers.get(camera_id)
            status['cameras'][camera_id] = {
                'connected': controller.is_connected() if controller else False,
                'last_event': controller.get_last_event_time() if controller else None,
                'events_count': controller.get_events_count() if controller else 0
            }

        return status


class ONVIFBarrierController:
    """ONVIF контролер за една камера"""

    def __init__(self, camera_ip, username, password, camera_type="onvif_generic",
                 barrier_name="Unknown", camera_id=None, port=80, dbname=None):
        self.camera_ip = camera_ip
        self.username = username
        self.password = password
        self.camera_type = camera_type.lower()
        self.barrier_name = barrier_name
        self.camera_id = camera_id or camera_ip
        self.port = port
        self.dbname = dbname

        # ONVIF services
        self.device_service = None
        self.event_service = None
        self.media_service = None

        # Monitoring
        self.monitoring_thread = None
        self.monitoring_active = False
        self.connected = False

        # Statistics
        self.last_event_time = None
        self.events_count = 0

    def connect(self):
        """Свързва се с ONVIF камерата"""
        if not ONVIF_AVAILABLE:
            return False

        try:
            _logger.info(f"🔌 ONVIF свързване с {self.camera_ip}...")

            # Device Service
            device_wsdl = f"http://{self.camera_ip}:{self.port}/onvif/device_service"
            self.device_service = Client(
                device_wsdl,
                wsse=UsernameToken(self.username, self.password)
            )

            # Тестваме връзката
            device_info = self.device_service.service.GetDeviceInformation()
            _logger.info(f"📋 ONVIF Device: {device_info.Manufacturer} {device_info.Model}")

            # Capabilities
            capabilities = self.device_service.service.GetCapabilities()

            # Event Service
            if hasattr(capabilities, 'Events') and capabilities.Events:
                try:
                    event_url = capabilities.Events.XAddr
                    self.event_service = Client(
                        f"{event_url}/event",
                        wsse=UsernameToken(self.username, self.password)
                    )
                    _logger.info("📡 ONVIF Event Service активен")
                except Exception as e:
                    _logger.warning(f"Event Service недостъпен: {e}")

            # Media Service
            if hasattr(capabilities, 'Media') and capabilities.Media:
                try:
                    media_url = capabilities.Media.XAddr
                    self.media_service = Client(
                        f"{media_url}/media",
                        wsse=UsernameToken(self.username, self.password)
                    )
                    _logger.info("🎥 ONVIF Media Service активен")
                except Exception as e:
                    _logger.warning(f"Media Service недостъпен: {e}")

            self.connected = True
            return True

        except Exception as e:
            _logger.error(f"❌ ONVIF грешка при свързване с {self.camera_ip}: {e}")
            return False

    def start_monitoring(self):
        """Стартира мониторинг"""
        if self.monitoring_active:
            return

        self.monitoring_active = True
        self.monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name=f"ONVIF-{self.camera_id}"
        )
        self.monitoring_thread.start()
        _logger.info(f"👁️ ONVIF мониторинг стартиран за {self.camera_id}")

    def stop_monitoring(self):
        """Спира мониторинга"""
        self.monitoring_active = False
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=3)

    def _monitoring_loop(self):
        """Основен мониторинг loop"""
        _logger.info(f"🔄 ONVIF мониторинг за {self.camera_id}")

        while self.monitoring_active and self.connected:
            try:
                # Проверяваме за събития според типа камера
                if self.camera_type in ['hikvision', 'dahua']:
                    self._check_camera_specific_events()
                else:
                    self._check_onvif_events()

                self._check_connection()
                time.sleep(2)

            except Exception as e:
                _logger.error(f"❌ ONVIF monitoring грешка за {self.camera_id}: {e}")
                time.sleep(5)

        _logger.info(f"🔄 ONVIF мониторинг спрян за {self.camera_id}")

    def _check_onvif_events(self):
        """Проверява стандартни ONVIF събития"""
        try:
            if not self.event_service:
                return

            # Pull messages
            try:
                messages = self.event_service.service.PullMessages({
                    'MessageLimit': 5,
                    'Timeout': 'PT1S'
                })

                if messages and hasattr(messages, 'NotificationMessage'):
                    for message in messages.NotificationMessage:
                        self._process_onvif_event(message)

            except Exception:
                pass  # Timeout е нормален

        except Exception as e:
            _logger.error(f"❌ ONVIF events грешка: {e}")

    def _check_camera_specific_events(self):
        """Проверява камера-специфични събития"""
        try:
            if self.camera_type == 'hikvision':
                self._check_hikvision_events()
            elif self.camera_type == 'dahua':
                self._check_dahua_events()

        except Exception as e:
            _logger.error(f"❌ Camera-specific events грешка: {e}")

    def _check_hikvision_events(self):
        """Hikvision HTTP API събития"""
        try:
            url = f"http://{self.camera_ip}/ISAPI/Event/notification/alertStream"

            response = requests.get(
                url,
                auth=HTTPDigestAuth(self.username, self.password),
                timeout=3,
                stream=True
            )

            if response.status_code == 200:
                for line in response.iter_lines(decode_unicode=True):
                    if not self.monitoring_active:
                        break

                    if line and ('eventType' in line or 'linedetection' in line.lower()):
                        self._process_hikvision_event(line)

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            _logger.error(f"❌ Hikvision events грешка: {e}")

    def _check_dahua_events(self):
        """Dahua HTTP API събития"""
        try:
            url = f"http://{self.camera_ip}/cgi-bin/eventManager.cgi?action=attach&codes=[All]"

            response = requests.get(
                url,
                auth=HTTPDigestAuth(self.username, self.password),
                timeout=3,
                stream=True
            )

            if response.status_code == 200:
                for line in response.iter_lines(decode_unicode=True):
                    if not self.monitoring_active:
                        break

                    if line and 'Code=' in line:
                        self._process_dahua_event(line)

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            _logger.error(f"❌ Dahua events грешка: {e}")

    def _process_onvif_event(self, message):
        """Обработва ONVIF събитие"""
        try:
            event_data = {
                'camera_id': self.camera_id,
                'camera_ip': self.camera_ip,
                'barrier_name': self.barrier_name,
                'event_type': 'onvif_generic',
                'timestamp': datetime.now().isoformat(),
                'raw_message': str(message)
            }

            # Парсиране на ONVIF съобщението
            if hasattr(message, 'Message') and hasattr(message.Message, 'Data'):
                data = message.Message.Data
                if hasattr(data, 'SimpleItem'):
                    for item in data.SimpleItem:
                        if hasattr(item, 'Name') and hasattr(item, 'Value'):
                            if item.Name == 'State' and item.Value == 'true':
                                event_data['event_type'] = 'motion_detected'
                                break

            self._create_odoo_event(event_data)

        except Exception as e:
            _logger.error(f"❌ ONVIF event обработка грешка: {e}")

    def _process_hikvision_event(self, line):
        """Обработва Hikvision събитие"""
        try:
            event_data = {
                'camera_id': self.camera_id,
                'camera_ip': self.camera_ip,
                'barrier_name': self.barrier_name,
                'event_type': 'hikvision_event',
                'timestamp': datetime.now().isoformat(),
                'raw_line': line
            }

            # Парсиране на Hikvision събития
            if 'linedetection' in line.lower():
                event_data['event_type'] = 'line_crossing'
            elif 'fielddetection' in line.lower():
                event_data['event_type'] = 'field_detection'
            elif 'motiondetection' in line.lower():
                event_data['event_type'] = 'motion_detected'

            self._create_odoo_event(event_data)

        except Exception as e:
            _logger.error(f"❌ Hikvision event обработка грешка: {e}")

    def _process_dahua_event(self, line):
        """Обработва Dahua събитие"""
        try:
            event_data = {
                'camera_id': self.camera_id,
                'camera_ip': self.camera_ip,
                'barrier_name': self.barrier_name,
                'event_type': 'dahua_event',
                'timestamp': datetime.now().isoformat(),
                'raw_line': line
            }

            # Парсиране на Dahua събития
            if 'CrossLineDetection' in line:
                event_data['event_type'] = 'line_crossing'
            elif 'CrossRegionDetection' in line:
                event_data['event_type'] = 'region_crossing'
            elif 'MotionDetect' in line:
                event_data['event_type'] = 'motion_detected'

            self._create_odoo_event(event_data)

        except Exception as e:
            _logger.error(f"❌ Dahua event обработка грешка: {e}")

    def _create_odoo_event(self, event_data):
        """Създава събитие в Odoo"""
        self.last_event_time = datetime.now()
        self.events_count += 1

        _logger.info(f"🚨 ONVIF събитие: {event_data['event_type']} от {self.camera_id}")

        try:
            # Създаваме thread за запис в Odoo
            threading.Thread(
                target=self._save_event_to_odoo,
                args=(event_data,),
                daemon=True
            ).start()

        except Exception as e:
            _logger.error(f"❌ Грешка при създаване на Odoo събитие: {e}")

    def _save_event_to_odoo(self, event_data):
        """Записва събитието в Odoo database"""
        try:
            if not self.dbname:
                return

            with registry(self.dbname).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})

                # Намираме камерата
                camera = env['lpr.camera.config'].search([
                    ('id', '=', int(self.camera_id))
                ], limit=1)

                if camera:
                    # Създаваме ONVIF event запис
                    env['onvif.camera.event'].create({
                        'camera_id': camera.id,
                        'event_type': event_data['event_type'],
                        'event_time': fields.Datetime.now(),
                        'raw_data': json.dumps(event_data, ensure_ascii=False, indent=2),
                    })

                    # Изпращаме bus notification
                    if hasattr(env, 'bus_bus'):
                        env['bus.bus']._sendone(
                            'onvif_camera_events',
                            'onvif_event',
                            {
                                'camera_id': self.camera_id,
                                'event_type': event_data['event_type'],
                                'barrier_name': self.barrier_name,
                                'timestamp': event_data['timestamp']
                            }
                        )

                cr.commit()

        except Exception as e:
            _logger.error(f"❌ Грешка при запис в Odoo: {e}")

    def _check_connection(self):
        """Проверява връзката"""
        try:
            if self.device_service:
                self.device_service.service.GetDeviceInformation()
                self.connected = True
            else:
                self.connected = False
        except:
            self.connected = False

    def is_connected(self):
        return self.connected

    def get_last_event_time(self):
        return self.last_event_time

    def get_events_count(self):
        return self.events_count