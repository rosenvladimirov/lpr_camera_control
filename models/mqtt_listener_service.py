# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""
MQTT Listener Service за LPR Camera Stream Module

Този модул обработва MQTT съобщения от LPR камери в background режим.

Конфигурация в odoo.conf:
------------------------
[options]
# MQTT Configuration for LPR Camera Stream
mqtt_host = mqtt-broker.local
mqtt_port = 1883
mqtt_user = <потребител>
mqtt_password = <парола>
mqtt_topics = lpr,lpr/+
mqtt_keepalive = 60
mqtt_qos = 0
mqtt_max_reconnect_attempts = 10
mqtt_reconnect_delay = 5
mqtt_tls = False
mqtt_debug = False
mqtt_max_log_payload = 500
mqtt_max_raw_payload_log = 1000

Описание на параметрите:
-----------------------
mqtt_host - IP адрес на MQTT брокъра
mqtt_port - Порт на MQTT брокъра (обикновено 1883)
mqtt_user - Потребителско име за MQTT автентикация
mqtt_password - Парола за MQTT автентикация
mqtt_topics - Списък от теми разделени със запетая (пример: lpr,lpr/+/)
mqtt_keepalive - Keepalive интервал в секунди
mqtt_qos - Quality of Service ниво (0, 1 или 2)
mqtt_max_reconnect_attempts - Максимален брой опити за преконектиране
mqtt_reconnect_delay - Секунди изчакване между опитите за преконектиране
mqtt_tls - Включва TLS/SSL шифроване (True/False)
mqtt_debug - Включва подробно логиране на MQTT комуникацията (True/False)
mqtt_max_log_payload - Максимален брой символи за логиране на payload
mqtt_max_raw_payload_log - Максимален брой символи за raw payload логиране

Пример за използване:
--------------------
# Стартиране на MQTT слушалката
service = env['mqtt.listener.service']
service.start_mqtt_listener()

# Проверка на статуса
status = service.get_listener_status()

# Тестване на връзката
test_result = service.test_mqtt_connection()
"""

import threading
import time
import json
import logging
import paho.mqtt.client as mqtt
from odoo import api, fields, models, registry, SUPERUSER_ID, tools

_logger = logging.getLogger(__name__)


class MqttListenerService(models.TransientModel):
    _name = 'mqtt.listener.service'
    _description = 'MQTT Listener Background Service'

    @api.model
    def get_mqtt_config(self):
        """Извлича MQTT конфигурацията от odoo.conf"""
        return {
            'host': tools.config.get('mqtt_host', 'mqtt-broker.local'),
            'port': int(tools.config.get('mqtt_port', 1883)),
            # Без фолбек стойности — креденшълите идват само от odoo.conf.
            # Ако липсват, връзката се проваля явно вместо да се пробва с чужда парола.
            'user': tools.config.get('mqtt_user', ''),
            'password': tools.config.get('mqtt_password', ''),
            'topics': tools.config.get('mqtt_topics', 'lpr,lpr/+').split(','),
            'keepalive': int(tools.config.get('mqtt_keepalive', 60)),
            'qos': int(tools.config.get('mqtt_qos', 0)),
        }

    @api.model
    def start_mqtt_listener(self):
        """Стартира MQTT слушалка в отделен thread"""
        if not hasattr(self.env.registry,
                       '_mqtt_listener_thread') or not self.env.registry._mqtt_listener_thread.is_alive():
            mqtt_config = self.get_mqtt_config()
            thread = MqttListenerThread(self.env.cr.dbname, mqtt_config)
            thread.daemon = True
            thread.start()
            self.env.registry._mqtt_listener_thread = thread
            _logger.info("MQTT слушалка стартирана")
            return True
        else:
            _logger.info("MQTT слушалка вече работи")
            return False

    @api.model
    def stop_mqtt_listener(self):
        """Спира MQTT слушалка"""
        if hasattr(self.env.registry, '_mqtt_listener_thread'):
            thread = self.env.registry._mqtt_listener_thread
            if thread.is_alive():
                thread.stop()
                thread.join(timeout=5)
                _logger.info("MQTT слушалка спряна")
                return True
        return False

    @api.model
    def get_listener_status(self):
        """Връща статуса на слушалката"""
        if hasattr(self.env.registry, '_mqtt_listener_thread'):
            thread = self.env.registry._mqtt_listener_thread
            return {
                'running': thread.is_alive(),
                'connected': getattr(thread, 'connected', False),
                'last_message_time': getattr(thread, 'last_message_time', None),
                'messages_received': getattr(thread, 'messages_received', 0),
                'config': thread.get_config_info() if hasattr(thread, 'get_config_info') else {}
            }
        return {'running': False, 'connected': False, 'config': {}}

    @api.model
    def test_mqtt_connection(self):
        """Тества MQTT връзката с текущата конфигурация"""
        try:
            mqtt_config = self.get_mqtt_config()

            # Логваме конфигурацията (без паролата)
            safe_config = mqtt_config.copy()
            safe_config['password'] = '***' if safe_config['password'] else None
            _logger.info(f"Тестване на MQTT връзка с конфигурация: {safe_config}")

            # Създаваме временен клиент за тест
            try:
                # За paho-mqtt 2.0+
                test_client = mqtt.Client(
                    client_id=f"odoo_test_{int(time.time())}",
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2
                )
            except (TypeError, AttributeError):
                # За по-стари версии
                test_client = mqtt.Client(f"odoo_test_{int(time.time())}")

            test_client.username_pw_set(mqtt_config['user'], mqtt_config['password'])

            # Опитваме се да се свържем
            result = test_client.connect(mqtt_config['host'], mqtt_config['port'], keepalive=10)

            if result == 0:
                test_client.disconnect()
                _logger.info(f"MQTT връзка успешна с {mqtt_config['host']}:{mqtt_config['port']}")
                return {'success': True, 'message': 'Връзката е успешна', 'config': safe_config}
            else:
                _logger.error(f"MQTT връзка неуспешна: код {result}")
                return {'success': False, 'message': f'Грешка при свързване: код {result}', 'config': safe_config}

        except Exception as e:
            _logger.error(f"Грешка при тестване на MQTT връзката: {e}")
            return {'success': False, 'message': f'Грешка: {str(e)}', 'config': {}}

    @api.model
    def restart_mqtt_listener(self):
        """Рестартира MQTT слушалката"""
        try:
            self.stop_mqtt_listener()
            time.sleep(1)
            return self.start_mqtt_listener()
        except Exception as e:
            _logger.error(f"Грешка при рестартиране на MQTT слушалката: {e}")
            return False


class MqttListenerThread(threading.Thread):
    """Background thread за MQTT слушане"""

    def __init__(self, dbname, mqtt_config):
        super().__init__()
        self.dbname = dbname
        self.client = None
        self.connected = False
        self.running = False
        self.last_message_time = None
        self.messages_received = 0
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = int(tools.config.get('mqtt_max_reconnect_attempts', 10))
        self.reconnect_delay = int(tools.config.get('mqtt_reconnect_delay', 5))

        # MQTT настройки от odoo.conf
        self.mqtt_host = mqtt_config['host']
        self.mqtt_port = mqtt_config['port']
        self.mqtt_user = mqtt_config['user']
        self.mqtt_pass = mqtt_config['password']
        self.mqtt_topics = [topic.strip() for topic in mqtt_config['topics']]
        self.mqtt_keepalive = mqtt_config['keepalive']
        self.mqtt_qos = mqtt_config['qos']
        self.client_id = f"odoo_listener_{int(time.time())}"

        # Логваме конфигурацията (без паролата)
        _logger.info(f"MQTT Thread конфигурация:")
        _logger.info(f"  Host: {self.mqtt_host}:{self.mqtt_port}")
        _logger.info(f"  User: {self.mqtt_user}")
        _logger.info(f"  Topics: {self.mqtt_topics}")
        _logger.info(f"  Client ID: {self.client_id}")
        _logger.info(f"  Keepalive: {self.mqtt_keepalive}s")
        _logger.info(f"  QoS: {self.mqtt_qos}")

    def get_config_info(self):
        """Връща информация за конфигурацията"""
        return {
            'host': self.mqtt_host,
            'port': self.mqtt_port,
            'user': self.mqtt_user,
            'topics': self.mqtt_topics,
            'client_id': self.client_id,
            'keepalive': self.mqtt_keepalive,
            'qos': self.mqtt_qos,
            'reconnect_attempts': self.reconnect_attempts,
            'max_reconnect_attempts': self.max_reconnect_attempts
        }

    def run(self):
        """Main thread loop"""
        self.running = True
        _logger.info("Стартиране на MQTT слушалка thread")

        while self.running:
            try:
                self.setup_mqtt_client()
                self.connect_to_mqtt()

                # Основен loop - слушаме за съобщения
                while self.running and self.connected:
                    self.client.loop(timeout=1.0)
                    time.sleep(0.1)

                # Ако връзката е прекъсната и все още работим, опитваме се да се преконектираме
                if self.running and not self.connected:
                    self.reconnect_attempts += 1
                    if self.reconnect_attempts <= self.max_reconnect_attempts:
                        _logger.warning(
                            f"MQTT връзката прекъсната. Опит за преконектиране {self.reconnect_attempts}/{self.max_reconnect_attempts}")
                        time.sleep(self.reconnect_delay)
                    else:
                        _logger.error(
                            f"Максимален брой опити за преконектиране достигнат ({self.max_reconnect_attempts})")
                        break

            except Exception as e:
                _logger.error(f"Грешка в MQTT слушалка: {e}")
                self.connected = False
                self.reconnect_attempts += 1

                if self.reconnect_attempts <= self.max_reconnect_attempts:
                    time.sleep(self.reconnect_delay)
                else:
                    _logger.error("Твърде много грешки, спиране на MQTT слушалката")
                    break

        self.disconnect()
        _logger.info("MQTT слушалка thread спряна")

    def setup_mqtt_client(self):
        """Настройка на MQTT клиента"""
        try:
            # За paho-mqtt 2.0+
            self.client = mqtt.Client(client_id=self.client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except (TypeError, AttributeError):
            # За по-стари версии
            try:
                self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
            except:
                self.client = mqtt.Client(self.client_id)

        # Настройване на callbacks
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_log = self.on_log

        # Автентикация
        if self.mqtt_user and self.mqtt_pass:
            self.client.username_pw_set(self.mqtt_user, self.mqtt_pass)

        # Допълнителни настройки от odoo.conf
        if tools.config.get('mqtt_tls', False):
            self.client.tls_set()
            _logger.info("MQTT TLS включен")

        _logger.info(f"MQTT клиент настроен: {self.client_id}")

    def connect_to_mqtt(self):
        """Свързване с MQTT брокъра"""
        try:
            _logger.info(f"Свързване с MQTT: {self.mqtt_host}:{self.mqtt_port}")
            result = self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=self.mqtt_keepalive)

            if result == 0:
                _logger.info("MQTT connect() извикан успешно")
            else:
                _logger.error(f"MQTT connect() връща грешка: {result}")
                raise Exception(f"Connect failed with code {result}")

        except Exception as e:
            _logger.error(f"Грешка при свързване с MQTT: {e}")
            raise

    def on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback при успешно свързване"""
        if rc == 0:
            self.connected = True
            self.reconnect_attempts = 0  # Нулираме брояча при успешна връзка
            _logger.info("MQTT свързан успешно")

            # Абониране за всички настроени теми
            for topic in self.mqtt_topics:
                result, mid = client.subscribe(topic, qos=self.mqtt_qos)
                if result == 0:
                    _logger.info(f"Абониран за тема: {topic} (QoS {self.mqtt_qos})")
                else:
                    _logger.error(f"Грешка при абонамент за тема {topic}: {result}")
        else:
            error_messages = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorised"
            }
            error_msg = error_messages.get(rc, f"Unknown error code {rc}")
            _logger.error(f"MQTT грешка при свързване: {error_msg}")
            self.connected = False

    def on_disconnect(self, client, userdata, rc, properties=None):
        """Callback при прекъсване на връзката"""
        self.connected = False
        if rc != 0:
            _logger.warning(f"MQTT връзката прекъсната неочаквано: {rc}")
        else:
            _logger.info("MQTT връзката прекъсната нормално")

    def on_log(self, client, userdata, level, buf):
        """MQTT log callback"""
        mqtt_debug = tools.config.get('mqtt_debug', False)
        if mqtt_debug:
            _logger.debug(f"MQTT Log: {buf}")

    def on_message(self, client, userdata, msg):
        """Callback при получаване на съобщение"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            self.last_message_time = fields.Datetime.now()
            self.messages_received += 1

            _logger.info(f"MQTT съобщение получено от тема '{topic}': {len(payload)} символа")

            # Ограничаваме логирането на payload ако е твърде голям
            max_log_payload = int(tools.config.get('mqtt_max_log_payload', 500))
            if len(payload) <= max_log_payload:
                _logger.debug(f"MQTT Payload: {payload}")
            else:
                _logger.debug(f"MQTT Payload (първите {max_log_payload} символа): {payload[:max_log_payload]}...")

            # Обработваме съобщението в отделен thread за да не блокираме MQTT loop
            processing_thread = threading.Thread(target=self.process_message, args=(topic, payload))
            processing_thread.daemon = True
            processing_thread.start()

        except Exception as e:
            _logger.error(f"Грешка при обработка на MQTT съобщение: {e}")

    def process_message(self, topic, payload):
        """Обработва получено съобщение в отделен thread"""
        try:
            # Парсираме JSON данните
            if payload.strip().startswith('{'):
                data = json.loads(payload)
            else:
                # Ако не е JSON, опитваме се да го интерпретираме
                data = {'raw_message': payload, 'topic': topic}

            # Създаваме нов registry за този thread
            with registry(self.dbname).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})

                # Създаваме LPR събитие
                lpr_event = env['lpr.event'].create_from_mqtt(data)

                if lpr_event:
                    _logger.info(f"LPR събитие създадено: {lpr_event.id} - {lpr_event.plate_number}")

                    # Commit промените
                    cr.commit()

                    # Изпращаме notification към активните потребители (опционално)
                    self.send_realtime_notification(env, lpr_event, data)

                else:
                    _logger.warning("Не успя да се създаде LPR събитие")

        except json.JSONDecodeError as e:
            _logger.warning(f"MQTT съобщение не е валиден JSON: {e}")
            # Можем да логваме raw съобщението за debug
            self.log_raw_message(topic, payload)
        except Exception as e:
            _logger.error(f"Грешка при обработка на MQTT съобщение: {e}")

    def send_realtime_notification(self, env, lpr_event, raw_data):
        """Изпраща real-time notification към frontend (опционално)"""
        try:
            # Можем да използваме bus notification за real-time updates
            if hasattr(env, 'bus_bus'):  # Odoo 18 bus модул
                env['bus.bus']._sendone(
                    'lpr_events',
                    'new_event',
                    {
                        'event_id': lpr_event.id,
                        'plate': lpr_event.plate_number,
                        'camera': lpr_event.camera_id.name,
                        'time': lpr_event.event_time.isoformat() if lpr_event.event_time else None,
                        'access_granted': lpr_event.access_granted,
                        'access_reason': lpr_event.access_reason,
                    }
                )
                _logger.debug("Bus notification изпратена")
        except Exception as e:
            _logger.warning(f"Не успя да изпрати bus notification: {e}")

    def log_raw_message(self, topic, payload):
        """Логва raw съобщения които не са JSON"""
        try:
            max_payload_log = int(tools.config.get('mqtt_max_raw_payload_log', 1000))

            with registry(self.dbname).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env['ir.logging'].create({
                    'name': 'MQTT Raw Message',
                    'type': 'server',
                    'level': 'INFO',
                    'message': f"Topic: {topic}\nPayload: {payload[:max_payload_log]}{'...' if len(payload) > max_payload_log else ''}",
                    'func': 'mqtt_listener',
                    'path': 'lpr_camera_control.mqtt_listener',
                })
                cr.commit()
        except Exception as e:
            _logger.error(f"Грешка при логване на raw съобщение: {e}")

    def stop(self):
        """Спира thread-а"""
        _logger.info("Получена команда за спиране на MQTT thread")
        self.running = False
        self.disconnect()

    def disconnect(self):
        """Прекъсва MQTT връзката"""
        if self.client and self.connected:
            try:
                self.client.disconnect()
                _logger.info("MQTT клиент разкачен")
            except Exception as e:
                _logger.error(f"Грешка при разкачване на MQTT клиент: {e}")
            finally:
                self.connected = False
