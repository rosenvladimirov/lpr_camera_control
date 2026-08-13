
/** @odoo-module **/

import { KanbanController } from "@web/views/kanban/kanban_controller";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { Component, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";

/**
 * LPR Camera Kanban Controller Extension
 * Слуша Bus шината за ping събития и актуализира цветните индикатори в реално време
 */
patch(KanbanController.prototype, {
    setup() {
        super.setup(...arguments);

        this.busService = useService("bus_service");
        this.notification = useService("notification");
        this.orm = useService("orm"); // Използваме orm вместо rpc

        // Проверяваме дали сме в LPR Camera модела
        this.isLprCameraModel = this.props.resModel === 'lpr.camera.config';

        if (this.isLprCameraModel) {
            this.busListeners = [];
            this.setupBusListeners();
        }

        onWillUnmount(() => {
            if (this.isLprCameraModel) {
                this.cleanupBusListeners();
            }
        });
    },

    setupBusListeners() {
        console.log('🚌 Настройване на Bus listeners за LPR Camera Kanban...');

        try {
            // Слушаме за ping резултати от отделни камери
            const pingResultListener = (payload) => this.handleCameraPingResult(payload);
            this.busService.subscribe("lpr_camera_ping_result", pingResultListener);
            this.busListeners.push({ event: "lpr_camera_ping_result", listener: pingResultListener });

            // Слушаме за обобщени ping резултати
            const pingSummaryListener = (payload) => this.handlePingSummary(payload);
            this.busService.subscribe("lpr_camera_ping_summary", pingSummaryListener);
            this.busListeners.push({ event: "lpr_camera_ping_summary", listener: pingSummaryListener });

            // Слушаме за LPR събития за актуализация на last_seen
            const lprEventListener = (payload) => {
                if (payload && payload.camera_name) {
                    this.handleLprEvent(payload);
                }
            };

            this.busService.subscribe("lpr_event_detected", lprEventListener);
            this.busListeners.push({ event: "lpr_event_detected", listener: lprEventListener });

            // Каналът се добавя веднъж, след като абонаментите са налице
            this.busService.addChannel("lpr_camera_control");

            console.log('✅ Bus listeners настроени успешно за LPR Camera Kanban');

        } catch (error) {
            console.error("❌ Грешка при настройване на Bus listeners:", error);
        }
    },

    cleanupBusListeners() {
        console.log('🧹 Почистване на Bus listeners за LPR Camera Kanban...');

        this.busListeners.forEach(({ event, listener }) => {
            try {
                this.busService.unsubscribe(event, listener);
            } catch (error) {
                console.warn(`⚠️ Грешка при премахване на listener ${event}:`, error);
            }
        });

        this.busListeners = [];
        console.log('✅ Bus listeners почистени');
    },

    handleCameraPingResult(data) {
        console.log('📍 Camera ping result получен:', data);

        const { camera_id, camera_name, ip_address, connected, message, message_type } = data;

        // Актуализираме визуалния статус на камерата
        this.updateCameraVisualStatus(camera_id, connected ? 'online' : 'offline');

        // Показваме нотификация ако е необходимо
        if (message_type === 'warning' || message_type === 'danger') {
            this.notification.add(message, {
                type: message_type === 'warning' ? 'warning' : 'danger',
                sticky: false,
                title: `Ping ${camera_name}`
            });
        }

        // Рефрешваме записа в kanban view
        this.refreshCameraRecord(camera_id);
    },

    handlePingSummary(data) {
        console.log('📊 Ping summary получен:', data);

        const { total_cameras, online_cameras, offline_cameras } = data;

        // Показваме обобщение в нотификация
        if (offline_cameras > 0) {
            this.notification.add(
                `Ping завършен: ${online_cameras} онлайн, ${offline_cameras} офлайн от общо ${total_cameras} камери`,
                {
                    type: 'warning',
                    sticky: false,
                    title: 'LPR Camera Ping Summary'
                }
            );
        } else if (total_cameras > 0) {
            this.notification.add(
                `Всички ${total_cameras} камери са онлайн! ✅`,
                {
                    type: 'success',
                    sticky: false,
                    title: 'LPR Camera Ping Summary'
                }
            );
        }

        // Рефрешваме целия kanban view за актуализиране на всички статуси
        this.refreshKanbanView();
    },

    handleLprEvent(data) {
        // При LPR събитие актуализираме last_seen на камерата
        if (data.camera_name) {
            console.log('🚗 LPR събитие от камера:', data.camera_name);

            // Намираме camera_id по име (ако е необходимо)
            // За момента просто рефрешваме view-то
            this.refreshKanbanView();
        }
    },

    updateCameraVisualStatus(cameraId, status) {
        console.log(`🎨 Актуализиране на визуален статус за камера ${cameraId}: ${status}`);

        try {
            // Намираме kanban картичката за тази камера
            const kanbanCard = document.querySelector(`[data-id="${cameraId}"]`);

            if (kanbanCard) {
                // Намираме индикатора за статус
                const statusIndicator = kanbanCard.querySelector('.fa-circle');
                const statusBadge = kanbanCard.querySelector('.o_kanban_record_bottom .badge');

                if (statusIndicator) {
                    // Премахваме старите класове
                    statusIndicator.classList.remove('text-success', 'text-danger', 'text-warning', 'text-muted');

                    // Добавяме новия клас според статуса
                    switch (status) {
                        case 'online':
                            statusIndicator.classList.add('text-success');
                            statusIndicator.title = 'Онлайн';
                            break;
                        case 'offline':
                            statusIndicator.classList.add('text-danger');
                            statusIndicator.title = 'Офлайн';
                            break;
                        case 'checking':
                            statusIndicator.classList.add('text-warning');
                            statusIndicator.title = 'Проверява се';
                            break;
                        default:
                            statusIndicator.classList.add('text-muted');
                            statusIndicator.title = 'Неизвестно';
                    }
                }

                if (statusBadge) {
                    // Актуализираме badge-а
                    statusBadge.classList.remove('badge-success', 'badge-danger', 'badge-warning', 'badge-secondary');

                    switch (status) {
                        case 'online':
                            statusBadge.classList.add('badge-success');
                            statusBadge.textContent = 'Online';
                            break;
                        case 'offline':
                            statusBadge.classList.add('badge-danger');
                            statusBadge.textContent = 'Offline';
                            break;
                        case 'checking':
                            statusBadge.classList.add('badge-warning');
                            statusBadge.textContent = 'Checking...';
                            break;
                        default:
                            statusBadge.classList.add('badge-secondary');
                            statusBadge.textContent = 'Unknown';
                    }
                }

                // Добавяме визуален feedback с анимация
                this.addUpdateAnimation(kanbanCard);
            }

        } catch (error) {
            console.error("❌ Грешка при актуализиране на визуален статус:", error);
        }
    },

    addUpdateAnimation(element) {
        // Добавяме кратка анимация за показване на актуализацията
        element.style.transition = 'all 0.3s ease';
        element.style.transform = 'scale(1.02)';
        element.style.boxShadow = '0 4px 12px rgba(0,123,255,0.3)';

        setTimeout(() => {
            element.style.transform = 'scale(1)';
            element.style.boxShadow = '';
        }, 300);
    },

    async refreshCameraRecord(cameraId) {
        try {
            // Рефрешваме конкретен запис
            console.log(`🔄 Рефрешване на запис за камера ${cameraId}`);

            // Reload на kanban view за да покаже актуализираните данни
            await this.model.root.load();
            this.render();

        } catch (error) {
            console.error("❌ Грешка при рефрешване на запис:", error);
        }
    },

    async refreshKanbanView() {
        try {
            console.log('🔄 Рефрешване на kanban view...');

            // Reload на цялото kanban view
            await this.model.root.load();
            this.render();

        } catch (error) {
            console.error("❌ Грешка при рефрешване на kanban view:", error);
        }
    },

    // Добавяме action за ping на всички камери
    async onPingAllCameras() {
        try {
            console.log('📡 Стартиране на ping на всички камери...');

            // Използваме orm.call вместо this.rpc
            const response = await this.orm.call(
                "lpr.camera.config",
                "action_ping_all_cameras",
                [[]] // args като празен списък с IDs
            );

            if (response && response.type === 'ir.actions.client') {
                // Показваме нотификацията от отговора
                this.notification.add(response.params.message, {
                    type: response.params.type || 'info',
                    sticky: response.params.sticky || false,
                    title: 'Ping All Cameras'
                });
            }

        } catch (error) {
            console.error("❌ Грешка при ping на всички камери:", error);
            this.notification.add("Грешка при ping на всички камери", {
                type: 'danger',
                sticky: false
            });
        }
    },

    // Добавяме action за проверка на ping service статус
    async onCheckPingServiceStatus() {
        try {
            console.log('📊 Проверка на ping service статус...');

            // Използваме orm.call вместо this.rpc
            const response = await this.orm.call(
                "lpr.camera.config",
                "get_ping_service_status",
                [[]] // args като празен списък
            );

            const status = response || {};
            const isRunning = status.running || false;
            const lastPing = status.last_ping_cycle ? new Date(status.last_ping_cycle).toLocaleString() : 'Няма';

            const message = `Ping Service: ${isRunning ? '🟢 Активен' : '🔴 Неактивен'}\n` +
                          `Последен ping: ${lastPing}\n` +
                          `Проверени камери: ${status.cameras_checked || 0}\n` +
                          `Онлайн: ${status.cameras_online || 0}, Офлайн: ${status.cameras_offline || 0}`;

            this.notification.add(message, {
                type: isRunning ? 'info' : 'warning',
                sticky: true,
                title: 'LPR Camera Ping Service Status'
            });

        } catch (error) {
            console.error("❌ Грешка при проверка на ping service:", error);
            this.notification.add("Грешка при проверка на ping service", {
                type: 'danger',
                sticky: false
            });
        }
    }
});

/**
 * LPR Camera Kanban Renderer Extension
 * Добавя допълнителни контроли в kanban view
 */
patch(KanbanRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.isLprCameraModel = this.props.list.model.config.resModel === 'lpr.camera.config';
    }
});

/**
 * CSS стилове за анимации и визуални подобрения
 */
const lprCameraKanbanCSS = `
<style>
/* LPR Camera Kanban Стилове */
.lpr-camera-kanban .o_kanban_record {
    transition: all 0.3s ease;
}

.lpr-camera-kanban .o_kanban_record:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

/* Статус индикатори */
.lpr-camera-status-indicator {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-right: 8px;
    animation: pulse 2s infinite;
}

.lpr-camera-status-indicator.online {
    background-color: #28a745;
}

.lpr-camera-status-indicator.offline {
    background-color: #dc3545;
}

.lpr-camera-status-indicator.checking {
    background-color: #ffc107;
}

.lpr-camera-status-indicator.unknown {
    background-color: #6c757d;
}

@keyframes pulse {
    0% { opacity: 1; }
    50% { opacity: 0.6; }
    100% { opacity: 1; }
}

/* Update анимация */
.lpr-camera-updating {
    animation: updating 0.6s ease;
}

@keyframes updating {
    0% { transform: scale(1); }
    50% { transform: scale(1.05); background-color: rgba(0,123,255,0.1); }
    100% { transform: scale(1); }
}

/* Ping control panel */
.lpr-camera-controls {
    background: #f8f9fa;
    padding: 10px;
    border-radius: 4px;
    margin-bottom: 15px;
    border: 1px solid #dee2e6;
}

.lpr-camera-controls .btn {
    margin-right: 8px;
    margin-bottom: 4px;
}

.lpr-ping-summary {
    font-size: 0.9em;
    color: #6c757d;
    margin-top: 8px;
}
</style>
`;

// Inject CSS styles
if (!document.querySelector('#lpr-camera-kanban-styles')) {
    const styleElement = document.createElement('div');
    styleElement.id = 'lpr-camera-kanban-styles';
    styleElement.innerHTML = lprCameraKanbanCSS;
    document.head.appendChild(styleElement);
}

/**
 * LPR Camera Kanban View Registration
 */
export const lprCameraKanbanView = {
    ...kanbanView,
    Controller: KanbanController,
    Renderer: KanbanRenderer,
};

// Регистрираме view-то за LPR Camera модела
registry.category("views").add("lpr_camera_kanban", lprCameraKanbanView);

console.log('✅ LPR Camera Kanban JS модул зареден успешно');