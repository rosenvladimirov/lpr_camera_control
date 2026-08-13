from . import controllers
from . import models


def pre_init_hook(cr, registry):
    """Hook който се изпълнява преди инсталиране на модула"""
    pass


def post_init_hook(cr, registry):
    """Hook който се изпълнява след инсталиране на модула"""
    from odoo import api, SUPERUSER_ID
    import logging

    _logger = logging.getLogger(__name__)

    try:
        with api.Environment.manage():
            env = api.Environment(cr, SUPERUSER_ID, {})

            # Стартираме MQTT слушалката автоматично
            mqtt_service = env['mqtt.listener.service']
            result = mqtt_service.start_mqtt_listener()

            if result:
                _logger.info("✅ MQTT слушалка стартирана успешно при инсталиране")
            else:
                _logger.warning("⚠️ MQTT слушалка вече работи или не може да бъде стартирана")

            # Стартираме ONVIF сървъра автоматично
            try:
                onvif_service = env['onvif.camera.service']
                onvif_result = onvif_service.start_onvif_server()

                if onvif_result:
                    _logger.info("✅ ONVIF Camera Server стартиран успешно при инсталиране")
                else:
                    _logger.warning("⚠️ ONVIF Camera Server вече работи или не може да бъде стартиран")
            except Exception as e:
                _logger.warning(
                    f"⚠️ ONVIF сървърът не може да бъде стартиран (нормално ако няма ONVIF библиотеки): {e}")

            # Стартираме автоматичното ping на LPR камерите
            try:
                camera_config_service = env['lpr.camera.config']
                ping_result = camera_config_service.start_camera_ping_service()

                if ping_result:
                    _logger.info("✅ LPR Camera Ping Service стартиран успешно при инсталиране")
                else:
                    _logger.warning("⚠️ LPR Camera Ping Service вече работи или не може да бъде стартиран")
            except Exception as e:
                _logger.warning(f"⚠️ LPR Camera Ping Service не може да бъде стартиран: {e}")

    except Exception as e:
        _logger.error(f"❌ Грешка при стартиране на services: {e}")


def uninstall_hook(cr, registry):
    """Hook който се изпълнява при деинсталиране"""
    from odoo import api, SUPERUSER_ID
    import logging

    _logger = logging.getLogger(__name__)

    try:
        with api.Environment.manage():
            env = api.Environment(cr, SUPERUSER_ID, {})

            # Спираме MQTT слушалката
            mqtt_service = env['mqtt.listener.service']
            result = mqtt_service.stop_mqtt_listener()

            if result:
                _logger.info("✅ MQTT слушалка спряна успешно при деинсталиране")
            else:
                _logger.info("ℹ️ MQTT слушалка не работеше или не може да бъде спряна")

            # Спираме ONVIF сървъра
            try:
                onvif_service = env['onvif.camera.service']
                onvif_result = onvif_service.stop_onvif_server()

                if onvif_result:
                    _logger.info("✅ ONVIF Camera Server спрян успешно при деинсталиране")
                else:
                    _logger.info("ℹ️ ONVIF Camera Server не работеше или не може да бъде спрян")
            except Exception as e:
                _logger.warning(f"⚠️ Грешка при спиране на ONVIF сървъра: {e}")

            # Спираме LPR Camera Ping Service
            try:
                camera_config_service = env['lpr.camera.config']
                ping_result = camera_config_service.stop_camera_ping_service()

                if ping_result:
                    _logger.info("✅ LPR Camera Ping Service спрян успешно при деинсталиране")
                else:
                    _logger.info("ℹ️ LPR Camera Ping Service не работеше или не може да бъде спрян")
            except Exception as e:
                _logger.warning(f"⚠️ Грешка при спиране на LPR Camera Ping Service: {e}")

    except Exception as e:
        _logger.error(f"❌ Грешка при спиране на services: {e}")
