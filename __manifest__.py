
{
    'name': 'LPR Camera Stream',
    'version': '18.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Camera stream for kiosk mode with LPR event listening',
    'description': '''
        This module adds:
        - Camera stream in kiosk mode
        - MQTT listener for LPR camera events (background service)
        - Extension of the attendance module
        - MQTT integration for real-time events
        - License plate recognition integration
        - Access control based on vehicle registry
        - Real-time notifications via bus system
        - Fleet module integration for vehicle management
        - ONVIF camera integration and monitoring
    ''',
    'author': 'SMARTSDYS-BG.COM',
    'website': 'https://github.com/SMARTSDYS-BG-COM/lpr_camera_control',
    'maintainer': 'SMARTSDYS-BG.COM',
    'contributors': [
        'Rosen Vladimirov <vladimirov.rosen@gmail.com>',
    ],
    'license': 'AGPL-3',
    'development_status': 'Beta',
    'depends': [
        'base',
        'hr',
        'hr_attendance',
        'fleet',
        'web',
        'bus',
        'product_manufacturer',  # OCA модул за производители
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_jobs.xml',
        'views/lpr_event_views.xml',
        'views/mqtt_service_views.xml',
        'views/onvif_camera_event_views.xml',
        'views/attendance_kiosk_inherit.xml',
        'views/car_registry_views.xml',
        'views/parking_session_views.xml',
        'views/webrtc_player_template.xml',
    ],
    'demo': [
        # 'demo/demo_cameras.xml',
        # 'demo/demo_car_registry.xml',
    ],
    'assets': {
        'web.assets_backend': [  # Добавяме за backend views
            'lpr_camera_control/static/src/js/lpr_camera_kanban.js',
        ],
        'web.assets_frontend': [
            'lpr_camera_control/static/src/css/kiosk_camera.css',
            'lpr_camera_control/static/src/js/kiosk_camera.js',
            'lpr_camera_control/static/src/js/attendance_kiosk_extension.js',
            'lpr_camera_control/static/src/xml/kiosk_camera_template.xml',
        ],
    },
    'external_dependencies': {
        'python': [
            'paho-mqtt',
            'pillow',
            'zeep',  # За ONVIF WSDL parsing
            'requests',  # За HTTP заявки към камерите
        ],
        'bin': [],
    },
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'pre_init_hook': 'pre_init_hook',
    'auto_install': False,
    'installable': True,
    'application': True,
    'sequence': 10,
    # 'images': [
    #     'lpr_camera_control/static/description/icon.png',
    #     # 'lpr_camera_control/static/description/banner.png',
    #     # 'lpr_camera_control/static/description/screenshot_1.png',
    #     # '/lpr_camera_controlstatic/description/screenshot_2.png',
    # ],
    'qweb': [],
    'bootstrap': False,
    'countries': ['BG'],
    'cloc_exclude': [
        'static/lib/**/*',
        'static/description/**/*',
        'demo/**/*',
    ],
    'price': 0.00,
    'currency': 'EUR',
    'support': 'vladimirov.rosen@gmail.com',
    'live_test_url': 'https://demo.smartsdys-bg.com/lpr_camera_control',
    'repository': 'https://github.com/SMARTSDYS-BG-COM/lpr_camera_control',
    'bug_tracker': 'https://github.com/SMARTSDYS-BG-COM/lpr_camera_control/issues',
    'documentation_url': 'https://github.com/SMARTSDYS-BG-COM/lpr_camera_control/wiki',
}