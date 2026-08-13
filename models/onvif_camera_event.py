from odoo import models, fields, api
import json
from datetime import datetime


class ONVIFCameraEvent(models.Model):
    _name = 'onvif.camera.event'
    _description = 'ONVIF Camera Events'
    _order = 'create_date desc'

    name = fields.Char('Event Name', compute='_compute_name', store=True)
    camera_id = fields.Many2one('lpr.camera.config', string='Camera', required=True, index=True)
    event_type = fields.Selection([
        ('motion_detected', 'Motion Detected'),
        ('line_crossing', 'Line Crossing'),
        ('field_detection', 'Field Detection'),
        ('region_crossing', 'Region Crossing'),
        ('onvif_generic', 'ONVIF Generic'),
        ('hikvision_event', 'Hikvision Event'),
        ('dahua_event', 'Dahua Event'),
    ], string='Event Type', required=True, index=True)

    event_time = fields.Datetime('Event Time', required=True, default=fields.Datetime.now, index=True)
    raw_data = fields.Text('Raw Data')

    # Processing status
    processed = fields.Boolean('Processed', default=False)
    processing_notes = fields.Text('Processing Notes')

    @api.depends('event_type', 'camera_id')
    def _compute_name(self):
        for record in self:
            if record.camera_id and record.event_type:
                record.name = f"{record.camera_id.name} - {record.event_type}"
            else:
                record.name = record.event_type or "Unknown Event"

    def action_mark_processed(self):
        """Маркира събитието като обработено"""
        self.processed = True
        self.processing_notes = f"Processed manually on {datetime.now()}"