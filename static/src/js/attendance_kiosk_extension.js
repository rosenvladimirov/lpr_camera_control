/** @odoo-module **/

// В Odoo 18 публичният киоск е Owl компонент в public_kiosk_app.js.
// Старият "@hr_attendance/js/kiosk_mode" не съществува — импортът му
// събаряше целия frontend бъндъл още при зареждане.
import publicKioskApp from "@hr_attendance/public_kiosk/public_kiosk_app";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { onWillDestroy } from "@odoo/owl";

// Един канал за целия модул; типовете съвпадат с тези, които
// изпраща сървърът през bus.bus._sendone(channel, type, payload).
const LPR_BUS_CHANNEL = "lpr_camera_control";

patch(publicKioskApp.kioskAttendanceApp.prototype, {

    setup() {
        super.setup(...arguments);

        this.busService = useService("bus_service");
        this.notification = useService("notification");

        this.cameraConfig = null;
        this.busConnected = false;
        this.autoCheckIn = true;
        this.lprSubscriptions = [];

        onWillDestroy(() => this.teardownLprIntegration());

        this.initLprIntegration();
    },

    async initLprIntegration() {
        try {
            // Зареждаме конфигурацията за LPR
            const response = await rpc("/lpr_camera/config");

            if (response.status === 'success' && response.cameras.length > 0) {
                this.cameraConfig = response.cameras;

                // Настройваме Bus listener вместо MQTT
                this.setupBusListener();

                this.addLprInterface();
                this.loadRecentEvents();
            }
        } catch (error) {
            console.error("Грешка при инициализация на LPR:", error);
        }
    },

    setupBusListener() {
        console.log('🚌 Настройване на Bus listener за attendance kiosk...');

        try {
            // В Odoo 18 се абонираме за ТИП събитие, а каналът се добавя
            // отделно; payload-ът идва директно, без event.detail.
            const handlers = {
                lpr_event_detected: (payload) => this.handleLprEventDetected(payload),
                lpr_access_result: (payload) => this.handleLprAccessResult(payload),
                lpr_attendance_created: (payload) => this.handleAttendanceCreated(payload),
                lpr_error: (payload) => this.handleLprError(payload),
            };

            for (const [type, handler] of Object.entries(handlers)) {
                this.busService.subscribe(type, handler);
                this.lprSubscriptions.push([type, handler]);
            }

            this.busService.addChannel(LPR_BUS_CHANNEL);

            this.busConnected = true;
            console.log('✅ Bus listener настроен успешно за attendance');
            this.displayLprStatus('connected');

            // Тестваме bus връзката
            this.testBusConnection();

        } catch (error) {
            console.error("❌ Грешка при настройване на Bus listener:", error);
            this.busConnected = false;
            this.displayLprStatus('disconnected');
        }
    },

    teardownLprIntegration() {
        for (const [type, handler] of this.lprSubscriptions || []) {
            this.busService.unsubscribe(type, handler);
        }
        this.lprSubscriptions = [];
        this.busService?.deleteChannel(LPR_BUS_CHANNEL);
    },

    async testBusConnection() {
        try {
            const response = await rpc("/lpr_camera/bus_status");
            console.log('🚌 Bus статус за attendance:', response);

            if (response.status === 'success' && response.bus_active) {
                this.busConnected = true;
                console.log('✅ Bus връзката е активна за attendance');
                this.displayLprStatus('connected');
            } else {
                console.warn('⚠️ Bus не е активен за attendance');
                this.busConnected = false;
                this.displayLprStatus('disconnected');
            }
        } catch (error) {
            console.error("❌ Грешка при проверка на Bus статус:", error);
            this.busConnected = false;
            this.displayLprStatus('disconnected');
        }
    },

    handleLprEventDetected(data) {
        console.log('🚗 LPR събитие засечено в attendance:', data.plate);

        // Показваме нотификация за новия номер
        this.displayMessage(`Засечен номер: ${data.plate}`, 'info');
    },

    async handleLprAccessResult(data) {
        console.log('🔒 Access result получен в attendance:', data.plate, data.access_granted ? '✅' : '❌');

        try {
            if (data.access_granted) {
                // Достъпът е разрешен
                const ownerInfo = data.owner_name || 'Неизвестен собственик';

                this.displayMessage(
                    `✅ ДОСТЪП РАЗРЕШЕН: ${ownerInfo}`,
                    'success'
                );

                // Ако е служител с автоматично отбелязване
                if (data.access_type === 'employee' && this.autoCheckIn) {
                    await this.performAutoCheckInByPlate(data.plate);
                }

                // Добавяме към панела с информация за собственика
                this.addEventToPanel({
                    plate: data.plate,
                    owner: ownerInfo,
                    access_granted: true,
                    reason: data.access_reason,
                    camera: data.camera_name
                });

            } else {
                // Достъпът е отказан
                this.displayMessage(
                    `❌ ДОСТЪП ОТКАЗАН: ${data.access_reason}`,
                    'danger'
                );

                // Добавяме към панела
                this.addEventToPanel({
                    plate: data.plate,
                    access_granted: false,
                    reason: data.access_reason,
                    camera: data.camera_name
                });
            }

        } catch (error) {
            console.error("Грешка при обработка на достъп:", error);
            this.displayMessage('Грешка при обработка на достъпа', 'danger');
        }
    },

    handleAttendanceCreated(data) {
        console.log('⏰ Attendance създаден в kiosk:', data.employee_name, data.check_type);

        this.displayMessage(
            `⏰ ${data.check_type === 'check_in' ? 'Влизане' : 'Излизане'}: ${data.employee_name}`,
            'success'
        );
    },

    handleLprError(data) {
        console.error('❌ LPR грешка в attendance:', data.error);

        this.displayMessage(
            `❌ Грешка при обработка на ${data.plate}: ${data.error}`,
            'danger'
        );
    },

    async performAutoCheckInByPlate(plateNumber) {
        try {
            // Търсим служителя по регистрирания автомобил
            const carRegistries = await rpc("/web/dataset/call_kw", {
                model: "car.registry",
                method: "search_read",
                args: [
                    [["license_plate", "=", plateNumber], ["employee_id", "!=", false]],
                    ["employee_id"]
                ],
                kwargs: { limit: 1 }
            });

            if (carRegistries.length > 0) {
                const employeeId = carRegistries[0].employee_id[0];
                await this.performAutoCheckIn(employeeId);
            } else {
                this.displayMessage('Номерът не е свързан със служител', 'warning');
            }

        } catch (error) {
            console.error("Грешка при намиране на служител по номер:", error);
            this.displayMessage('Грешка при автоматично отбелязване', 'danger');
        }
    },

    async performAutoCheckIn(employeeId) {
        try {
            // Извършваме автоматично отбелязване
            await rpc("/web/dataset/call_kw", {
                model: "hr.attendance",
                method: "attendance_action_change",
                args: [[employeeId]],
                kwargs: {}
            });

            // Зареждаме информацията за служителя
            const employees = await rpc("/web/dataset/call_kw", {
                model: "hr.employee",
                method: "read",
                args: [[employeeId], ["name"]],
                kwargs: {}
            });

            const employeeName = employees.length > 0 ? employees[0].name : 'Неизвестен';
            this.displayMessage(`⏰ Отбелязване за ${employeeName} успешно!`, 'success');

        } catch (error) {
            console.error("Грешка при автоматично отбелязване:", error);
            this.displayMessage('Грешка при автоматично отбелязване', 'danger');
        }
    },

    async loadRecentEvents() {
        try {
            const response = await rpc("/lpr_camera/recent_events", { limit: 5 });

            if (response.status === 'success') {
                const eventsPanel = document.getElementById('lpr-recent-events');
                if (eventsPanel) {
                    eventsPanel.innerHTML = ''; // Изчистваме панела

                    response.events.forEach(event => {
                        this.addEventToPanel({
                            plate: event.plate_number,
                            owner: event.owner_name,
                            access_granted: event.access_granted,
                            reason: event.access_reason,
                            camera: event.camera_name,
                            time: new Date(event.event_time).toLocaleTimeString(),
                            isHistorical: true
                        });
                    });
                }
            }
        } catch (error) {
            console.error("Грешка при зареждане на последни събития:", error);
        }
    },

    addLprInterface() {
        // Добавяме LPR интерфейс към attendance киоска
        const kioskContainer = document.querySelector('.o_hr_attendance_kiosk_mode');
        if (kioskContainer) {
            const lprPanel = document.createElement('div');
            lprPanel.className = 'lpr-panel';
            lprPanel.innerHTML = `
                <div class="lpr-header">
                    <h4>🚗 LPR Система за Достъп</h4>
                    <span class="lpr-status" id="lpr-status">Свързване...</span>
                </div>
                <div class="lpr-controls">
                    <button id="lpr-refresh" class="btn btn-sm btn-secondary">🔄 Обнови</button>
                    <button id="lpr-toggle-auto" class="btn btn-sm btn-primary" data-auto="true">
                        ⚡ Авто: ВКЛ
                    </button>
                    <button id="lpr-test-bus" class="btn btn-sm btn-info">🧪 Test Bus</button>
                </div>
                <div class="lpr-recent-events" id="lpr-recent-events">
                    <div class="loading">Зареждане на последни събития...</div>
                </div>
            `;

            kioskContainer.appendChild(lprPanel);

            // Добавяме event listeners за бутоните
            this.setupLprControls();
        }
    },

    setupLprControls() {
        const refreshBtn = document.getElementById('lpr-refresh');
        const toggleAutoBtn = document.getElementById('lpr-toggle-auto');
        const testBusBtn = document.getElementById('lpr-test-bus');

        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                this.loadRecentEvents();
                this.displayMessage('Събития обновени', 'info');
            });
        }

        if (toggleAutoBtn) {
            this.autoCheckIn = true; // По подразбиране е включено

            toggleAutoBtn.addEventListener('click', () => {
                this.autoCheckIn = !this.autoCheckIn;
                const isAuto = this.autoCheckIn;

                toggleAutoBtn.textContent = `⚡ Авто: ${isAuto ? 'ВКЛ' : 'ИЗКЛ'}`;
                toggleAutoBtn.className = `btn btn-sm ${isAuto ? 'btn-primary' : 'btn-secondary'}`;
                toggleAutoBtn.setAttribute('data-auto', isAuto);

                this.displayMessage(
                    `Автоматичното отбелязване е ${isAuto ? 'включено' : 'изключено'}`,
                    'info'
                );
            });
        }

        if (testBusBtn) {
            testBusBtn.addEventListener('click', async () => {
                await this.testBusNotification();
            });
        }
    },

    async testBusNotification() {
        try {
            const response = await rpc("/lpr_camera/test_bus");
            console.log('🧪 Test bus response от attendance:', response);

            if (response.status === 'success') {
                this.displayMessage("Test bus notification изпратена", 'info');
            } else {
                this.displayMessage(`Грешка при test: ${response.message}`, 'danger');
            }
        } catch (error) {
            console.error("Грешка при test bus от attendance:", error);
            this.displayMessage("Грешка при изпращане на test", 'danger');
        }
    },

    displayLprStatus(status) {
        const statusEl = document.getElementById('lpr-status');
        if (statusEl) {
            statusEl.textContent = status === 'connected' ? '🟢 Bus Свързан' : '🔴 Bus Прекъснат';
            statusEl.className = `lpr-status ${status}`;
        }
    },

    displayMessage(message, type = 'info') {
        // Показваме съобщение в attendance интерфейса
        if (this.notification) {
            this.notification.add(message, { type: type, sticky: false });
        }

        console.log(`LPR Attendance [${type}]: ${message}`);
    },

    addEventToPanel(eventInfo) {
        const eventsPanel = document.getElementById('lpr-recent-events');
        if (eventsPanel) {
            // Премахваме loading съобщението ако съществува
            const loading = eventsPanel.querySelector('.loading');
            if (loading) {
                loading.remove();
            }

            const eventDiv = document.createElement('div');
            const accessClass = eventInfo.access_granted ? 'access-granted' : 'access-denied';
            const timeStr = eventInfo.time || new Date().toLocaleTimeString();
            const isHistorical = eventInfo.isHistorical ? 'historical' : '';

            eventDiv.className = `lpr-event ${accessClass} ${isHistorical}`;
            eventDiv.innerHTML = `
                <div class="event-header">
                    <span class="event-plate">${eventInfo.plate}</span>
                    <span class="event-time">${timeStr}</span>
                </div>
                <div class="event-details">
                    ${eventInfo.owner ? `<div class="event-owner">👤 ${eventInfo.owner}</div>` : ''}
                    <div class="event-status ${accessClass}">
                        ${eventInfo.access_granted ? '✅' : '❌'} ${eventInfo.reason || 'Няма информация'}
                    </div>
                    ${eventInfo.camera ? `<div class="event-camera">📹 ${eventInfo.camera}</div>` : ''}
                </div>
            `;

            eventsPanel.insertBefore(eventDiv, eventsPanel.firstChild);

            // Запазваме само последните 10 събития
            while (eventsPanel.children.length > 10) {
                eventsPanel.removeChild(eventsPanel.lastChild);
            }

            // Добавяме анимация за нови събития
            if (!eventInfo.isHistorical) {
                eventDiv.classList.add('new-event');
                setTimeout(() => {
                    eventDiv.classList.remove('new-event');
                }, 3000);
            }
        }
    },
});
