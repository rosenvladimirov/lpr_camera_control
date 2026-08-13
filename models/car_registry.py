from odoo import models, fields, api
from datetime import datetime


class CarRegistry(models.Model):
    _name = 'car.registry'
    _description = 'Car Registry for LPR Access Control'
    _rec_name = 'display_name'
    _order = 'license_plate'

    # Основна информация за автомобила
    license_plate = fields.Char('License Plate', required=True, index=True,
                                help='License plate number (normalized)')
    license_plate_original = fields.Char('Original License Plate',
                                         help='Original format from registration')

    # Връзки
    employee_id = fields.Many2one('hr.employee', string='Employee', index=True,
                                  help='Employee who owns this car')
    partner_id = fields.Many2one('res.partner', string='Partner/Visitor', index=True,
                                 help='External partner/visitor who owns this car')
    fleet_vehicle_id = fields.Many2one('fleet.vehicle', string='Fleet Vehicle', index=True,
                                       help='Connected fleet vehicle')

    # Информация за автомобила
    make = fields.Char('Car Make', help='e.g. BMW, Mercedes')
    model = fields.Char('Car Model', help='e.g. X5, C-Class')
    color = fields.Char('Color')
    year = fields.Integer('Year')

    # Контрол на достъпа
    is_active = fields.Boolean('Active', default=True, index=True)
    access_type = fields.Selection([
        ('employee', 'Employee'),
        ('visitor', 'Visitor'),
        ('contractor', 'Contractor'),
        ('delivery', 'Delivery'),
        ('vip', 'VIP'),
        ('blacklist', 'Blacklisted')
    ], string='Access Type', default='employee', required=True, index=True)

    # Времеви контрол
    access_start_date = fields.Date('Access Start Date', default=fields.Date.today)
    access_end_date = fields.Date('Access End Date', help='Leave empty for permanent access')

    # Време на достъп
    access_time_start = fields.Float('Access Time Start', default=0.0,
                                     help='Start time in hours (0-24)')
    access_time_end = fields.Float('Access Time End', default=24.0,
                                   help='End time in hours (0-24)')

    # Дни от седмицата
    access_monday = fields.Boolean('Monday', default=True)
    access_tuesday = fields.Boolean('Tuesday', default=True)
    access_wednesday = fields.Boolean('Wednesday', default=True)
    access_thursday = fields.Boolean('Thursday', default=True)
    access_friday = fields.Boolean('Friday', default=True)
    access_saturday = fields.Boolean('Saturday', default=False)
    access_sunday = fields.Boolean('Sunday', default=False)

    # Разрешени камери/зони
    # TODO: Създайте модела 'lpr.camera.config' или използвайте съществуващ
    # allowed_cameras = fields.Many2many('lpr.camera.config', string='Allowed Cameras',
    #                                    help='Leave empty to allow all cameras')

    # Статистики
    total_entries = fields.Integer('Total Entries', compute='_compute_statistics', store=True)
    last_seen = fields.Datetime('Last Seen', compute='_compute_statistics', store=True)

    # Бележки
    notes = fields.Text('Notes')

    # Computed fields
    display_name = fields.Char('Display Name', compute='_compute_display_name', store=True)
    owner_name = fields.Char('Owner', compute='_compute_owner_name', store=True)

    @api.depends('license_plate', 'employee_id', 'partner_id', 'fleet_vehicle_id')
    def _compute_display_name(self):
        for record in self:
            owner = record.employee_id.name if record.employee_id else (
                record.partner_id.name if record.partner_id else
                (
                    record.fleet_vehicle_id.driver_id.name if record.fleet_vehicle_id and record.fleet_vehicle_id.driver_id else 'Неизвестен')
            )
            record.display_name = f"{record.license_plate} ({owner})"

    @api.depends('employee_id', 'partner_id', 'fleet_vehicle_id')
    def _compute_owner_name(self):
        for record in self:
            if record.employee_id:
                record.owner_name = record.employee_id.name
            elif record.partner_id:
                record.owner_name = record.partner_id.name
            elif record.fleet_vehicle_id and record.fleet_vehicle_id.driver_id:
                record.owner_name = record.fleet_vehicle_id.driver_id.name
            else:
                record.owner_name = 'Неизвестен'

    @api.depends('license_plate')
    def _compute_statistics(self):
        for record in self:
            events = self.env['lpr.event'].search([
                ('plate_number_normalized', '=', record.license_plate)
            ])
            record.total_entries = len(events)
            record.last_seen = max(events.mapped('event_time')) if events else False

    @api.model
    def create(self, vals):
        """Нормализираме номера при създаване"""
        if 'license_plate' in vals:
            vals['license_plate_original'] = vals['license_plate']
            vals['license_plate'] = self._normalize_license_plate(vals['license_plate'])
        return super().create(vals)

    def write(self, vals):
        """Нормализираме номера при промяна"""
        if 'license_plate' in vals:
            vals['license_plate_original'] = vals['license_plate']
            vals['license_plate'] = self._normalize_license_plate(vals['license_plate'])
        return super().write(vals)

    def _normalize_license_plate(self, plate):
        """Нормализира регистрационния номер"""
        if not plate:
            return plate
        # Премахваме интервали, правим главни букви
        normalized = ''.join(plate.split()).upper()
        # Можем да добавим още правила за нормализация
        return normalized

    @api.model
    def find_by_plate(self, plate_number):
        """Търси автомобил по номер включително и във fleet модула"""
        normalized_plate = self._normalize_license_plate(plate_number)

        # Първо търсим в car.registry
        car_record = self.search([
            ('license_plate', '=', normalized_plate),
            ('is_active', '=', True)
        ])

        if car_record:
            return car_record

        # Ако не намерим в car.registry, търсим във fleet.vehicle
        fleet_vehicles = self._search_in_fleet(normalized_plate)

        if fleet_vehicles:
            # Създаваме car.registry записи за намерените fleet vehicles
            created_records = self.env['car.registry']
            for vehicle in fleet_vehicles:
                car_record = self._create_from_fleet_vehicle(vehicle)
                if car_record:
                    created_records += car_record
            return created_records

        return self.env['car.registry']

    def _search_in_fleet(self, normalized_plate):
        """Търси във fleet модула"""
        if not self.env['ir.module.module'].search([('name', '=', 'fleet'), ('state', '=', 'installed')]):
            return self.env['fleet.vehicle']

        # Търсим във fleet.vehicle по license_plate
        fleet_vehicles = self.env['fleet.vehicle'].search([
            ('license_plate', 'ilike', normalized_plate.replace(' ', '%')),
            ('active', '=', True)
        ])

        # Опитваме се и с различни формати на номера
        if not fleet_vehicles:
            # Опитваме се без интервали
            plate_no_spaces = normalized_plate.replace(' ', '')
            fleet_vehicles = self.env['fleet.vehicle'].search([
                ('license_plate', 'ilike', f'%{plate_no_spaces}%'),
                ('active', '=', True)
            ])

        # Опитваме се и с интервали между буквите и цифрите
        if not fleet_vehicles and len(normalized_plate) >= 6:
            # Български формат: AB1234CD или A1234BC
            import re
            if re.match(r'^[A-Z]{1,2}\d{4}[A-Z]{1,2}$', normalized_plate):
                # Добавяме интервал между буквите и цифрите
                formatted_plate = re.sub(r'([A-Z]+)(\d+)([A-Z]+)', r'\1 \2 \3', normalized_plate)
                fleet_vehicles = self.env['fleet.vehicle'].search([
                    ('license_plate', 'ilike', formatted_plate),
                    ('active', '=', True)
                ])

        return fleet_vehicles

    def _create_from_fleet_vehicle(self, fleet_vehicle):
        """Създава car.registry запис от fleet.vehicle"""
        try:
            # Проверяваме дали вече не съществува
            existing = self.search([
                ('fleet_vehicle_id', '=', fleet_vehicle.id)
            ])
            if existing:
                return existing

            vals = {
                'license_plate': fleet_vehicle.license_plate or '',
                'license_plate_original': fleet_vehicle.license_plate or '',
                'fleet_vehicle_id': fleet_vehicle.id,
                'make': fleet_vehicle.brand_id.name if fleet_vehicle.brand_id else '',
                'model': fleet_vehicle.model_id.name if fleet_vehicle.model_id else '',
                'year': fleet_vehicle.model_year,
                'color': fleet_vehicle.color,
                'notes': f'Автоматично създадено от Fleet Vehicle: {fleet_vehicle.name}',
                'access_type': 'employee' if fleet_vehicle.driver_id else 'visitor',
            }

            # Свързваме с employee ако fleet vehicle има driver
            if fleet_vehicle.driver_id:
                # Търсим hr.employee за този partner
                employee = self.env['hr.employee'].search([
                    ('work_contact_id', '=', fleet_vehicle.driver_id.id)
                ], limit=1)
                if employee:
                    vals['employee_id'] = employee.id
                else:
                    vals['partner_id'] = fleet_vehicle.driver_id.id

            car_record = self.create(vals)
            return car_record

        except Exception as e:
            self.env['ir.logging'].sudo().create({
                'name': 'CarRegistry Fleet Integration',
                'type': 'server',
                'level': 'WARNING',
                'message': f'Грешка при създаване на car.registry от fleet.vehicle {fleet_vehicle.id}: {str(e)}',
                'func': '_create_from_fleet_vehicle',
            })
            return self.env['car.registry']

    def check_access(self, camera_id=None):
        """Проверява дали автомобилът има достъп"""
        self.ensure_one()

        if not self.is_active:
            return False, "Автомобилът е деактивиран"

        if self.access_type == 'blacklist':
            return False, "Автомобилът е в черния списък"

        # Проверка на дата
        today = fields.Date.today()
        if self.access_start_date and today < self.access_start_date:
            return False, f"Достъпът започва от {self.access_start_date}"

        if self.access_end_date and today > self.access_end_date:
            return False, f"Достъпът е изтекъл на {self.access_end_date}"

        # Проверка на ден от седмицата
        weekday = datetime.now().weekday()  # 0=Monday, 6=Sunday
        weekday_fields = [
            'access_monday', 'access_tuesday', 'access_wednesday',
            'access_thursday', 'access_friday', 'access_saturday', 'access_sunday'
        ]

        if not getattr(self, weekday_fields[weekday]):
            return False, "Няма достъп в този ден от седмицата"

        # Проверка на час
        now_hour = datetime.now().hour + datetime.now().minute / 60.0
        if not (self.access_time_start <= now_hour <= self.access_time_end):
            return False, f"Достъп разрешен между {self.access_time_start:.1f}h и {self.access_time_end:.1f}h"

        # Проверка на камера/зона (ако имаме allowed_cameras)
        # if camera_id and self.allowed_cameras:
        #     if camera_id not in self.allowed_cameras.ids:
        #         return False, "Няма достъп за тази камера/зона"

        return True, "Достъп разрешен"

    @api.model
    def sync_with_fleet(self):
        """Синхронизира всички fleet vehicles с car registry"""
        if not self.env['ir.module.module'].search([('name', '=', 'fleet'), ('state', '=', 'installed')]):
            return False

        fleet_vehicles = self.env['fleet.vehicle'].search([('active', '=', True)])
        created_count = 0

        for vehicle in fleet_vehicles:
            if vehicle.license_plate:
                existing = self.search([
                    ('fleet_vehicle_id', '=', vehicle.id)
                ])
                if not existing:
                    car_record = self._create_from_fleet_vehicle(vehicle)
                    if car_record:
                        created_count += 1

        return created_count

    def action_sync_fleet_data(self):
        """Action за синхронизиране на fleet данни"""
        if self.fleet_vehicle_id:
            # Актуализираме данните от fleet vehicle
            vehicle = self.fleet_vehicle_id
            self.write({
                'make': vehicle.brand_id.name if vehicle.brand_id else self.make,
                'model': vehicle.model_id.name if vehicle.model_id else self.model,
                'year': vehicle.model_year or self.year,
                'color': vehicle.color or self.color,
            })

            # Актуализираме owner информацията
            if vehicle.driver_id and not self.employee_id and not self.partner_id:
                employee = self.env['hr.employee'].search([
                    ('work_contact_id', '=', vehicle.driver_id.id)
                ], limit=1)
                if employee:
                    self.employee_id = employee.id
                else:
                    self.partner_id = vehicle.driver_id.id

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'Данните от Fleet модула са синхронизирани успешно!',
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'Няма свързан Fleet Vehicle за синхронизиране.',
                    'type': 'warning',
                }
            }
