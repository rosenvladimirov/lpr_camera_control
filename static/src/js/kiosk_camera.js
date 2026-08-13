
/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class KioskCameraComponent extends Component {
    static template = "lpr_camera_stream.KioskCameraTemplate";

    setup() {
        console.log("🔍 Налични сервиси:", this.env.services ? Object.keys(this.env.services) : "Няма services");

        // Опитваме се да заредим сервисите безопасно
        try {
            this.notification = useService("notification");
        } catch (e) {
            console.warn("Notification service не е намерен:", e);
            this.notification = null;
        }

        // Опитваме различни варианти за bus сервиса
        this.bus = null;
        const busServiceNames = ["bus", "bus_service", "longpolling", "websocket"];

        for (const serviceName of busServiceNames) {
            try {
                this.bus = useService(serviceName);
                console.log(`✅ Намерен bus сервис: ${serviceName}`);
                break;
            } catch (e) {
                console.warn(`Bus service '${serviceName}' не е намерен:`, e);
            }
        }

        if (!this.bus) {
            console.warn("❌ Няма наличен bus сервис - ще използваме polling");
        }

        this.state = useState({
            camera: null,
            events: [],
            isConnected: false,
            mqttStatus: 'disconnected',
            currentEvent: null,
            overlayVisible: false,
            busConnected: false
        });

        this.mqttListener = null;
        this.eventUpdateInterval = null;
        this.overlayTimeout = null;
        this.busListener = null;
        this.busPollingInterval = null;
        this.lastEventCheck = null;

        onMounted(() => {
            this.initializeKiosk();
            if (this.bus) {
                this.setupBusListener();
            } else {
                this.setupEventPolling();
            }
        });

        onWillUnmount(() => {
            this.cleanup();
        });
    }

    // =============== VISUAL EFFECTS ===============

    triggerFlashEffect(success = true) {
        // Flash ефект на цялата страница
        const kioskContainer = document.querySelector('.o_hr_attendance_kiosk_mode, body, .lpr-kiosk-container');
        if (kioskContainer) {
            const flashClass = success ? 'lpr-flash-green' : 'lpr-flash-red';
            kioskContainer.classList.add(flashClass);

            setTimeout(() => {
                kioskContainer.classList.remove(flashClass);
            }, 800);
        }
    }

    triggerPulseEffect(element) {
        // Pulse ефект на конкретен елемент
        if (element) {
            element.classList.add('lpr-pulse');
            setTimeout(() => {
                element.classList.remove('lpr-pulse');
            }, 1500);
        }
    }

    triggerShakeEffect(element) {
        // Shake ефект за грешки
        if (element) {
            element.classList.add('lpr-shake');
            setTimeout(() => {
                element.classList.remove('lpr-shake');
            }, 600);
        }
    }

    showOverlayEffect(success = true) {
        // Overlay ефект
        const overlay = document.querySelector('.event-overlay, .overlay-content');
        if (overlay) {
            const overlayClass = success ? 'lpr-overlay-success' : 'lpr-overlay-error';
            overlay.classList.add(overlayClass);

            setTimeout(() => {
                overlay.classList.remove(overlayClass);
            }, success ? 3000 : 5000);
        }
    }

    triggerParkingEffect(eventType) {
        // Паркинг ефекти
        const parkingPanel = document.querySelector('.lpr-panel, .events-section');
        if (parkingPanel) {
            const effectClass = eventType === 'entry' ? 'lpr-parking-entry' : 'lpr-parking-exit';
            parkingPanel.classList.add(effectClass);

            setTimeout(() => {
                parkingPanel.classList.remove(effectClass);
            }, 1000);
        }
    }

    // =============== HELPER METHODS ===============

    async makeJsonRpcCall(url, data = {}) {
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '',
                },
                body: JSON.stringify(data)
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`❌ Грешка при ${url}:`, error);
            throw error;
        }
    }

    // =============== BUS LISTENER METHODS ===============

    setupBusListener() {
        console.log('🚌 Настройване на Bus listener...');

        if (!this.bus) {
            console.error("Bus service не е наличен");
            this.state.busConnected = false;
            return;
        }

        try {
            // Слушаме за LPR събития от контролера
            this.bus.addEventListener("lpr_camera_stream", (event) => {
                console.log("🚌 Bus събитие получено:", event.detail);
                this.handleBusEvent(event.detail);
            });

            this.state.busConnected = true;
            console.log('✅ Bus listener настроен успешно');

            // Тестваме bus връзката
            this.testBusConnection();

        } catch (error) {
            console.error("❌ Грешка при настройване на Bus listener:", error);
            this.state.busConnected = false;
            // Fallback към polling ако bus не работи
            this.setupEventPolling();
        }
    }

    // =============== EVENT POLLING METHODS ===============

    setupEventPolling() {
        console.log('🔄 Настройване на event polling...');

        // Стартираме polling за нови събития на всеки 2 секунди
        this.busPollingInterval = setInterval(() => {
            this.pollForNewEvents();
        }, 2000);

        this.state.busConnected = true;
        console.log('✅ Event polling настроен успешно');

        // Тестваме bus връзката
        this.testBusConnection();
    }

    async pollForNewEvents() {
        try {
            // Проверяваме за нови събития от последния път
            const response = await this.makeJsonRpcCall("/lpr_camera/recent_events", {
                limit: 5,
                since: this.lastEventCheck
            });

            if (response.status === 'success' && response.events.length > 0) {
                // Обработваме новите събития
                const newEvents = response.events.filter(event => {
                    if (!this.lastEventCheck) return true;
                    return new Date(event.event_time) > new Date(this.lastEventCheck);
                });

                newEvents.forEach(event => {
                    this.processPolledEvent(event);
                });

                if (newEvents.length > 0) {
                    this.lastEventCheck = new Date().toISOString();
                }
            }
        } catch (error) {
            console.error("❌ Грешка при polling за събития:", error);
            this.state.busConnected = false;
        }
    }

    processPolledEvent(event) {
        // Симулираме bus събития базирани на event данните
        if (event.processing_status === 'pending') {
            this.handleLprEventDetected({
                plate: event.plate_number,
                camera_name: event.camera_name,
                timestamp: event.event_time
            });
        } else if (event.processing_status === 'processed' || event.processing_status === 'access_denied') {
            this.handleAccessResult({
                event_id: event.id,
                plate: event.plate_number,
                access_granted: event.access_granted,
                access_reason: event.access_reason,
                owner_name: event.owner_name,
                event_time: event.event_time,
                processing_status: event.processing_status
            });
        }
    }

    async testBusConnection() {
        try {
            const response = await this.makeJsonRpcCall("/lpr_camera/bus_status");
            console.log('🚌 Bus статус:', response);

            if (response.status === 'success' && response.bus_active) {
                this.state.busConnected = true;
                console.log('✅ Bus връзката е активна');
            } else {
                console.warn('⚠️ Bus не е активен');
                this.state.busConnected = false;
            }
        } catch (error) {
            console.error("❌ Грешка при проверка на Bus статус:", error);
            this.state.busConnected = false;
        }
    }

    // =============== BUS EVENT HANDLERS ===============

    handleBusEvent(eventDetail) {
        const { type, data } = eventDetail;

        console.log(`🚌 Обработка на Bus събитие: ${type}`, data);

        switch (type) {
            case 'lpr_event_detected':
                this.handleLprEventDetected(data);
                break;

            case 'lpr_access_result':
                this.handleAccessResult(data);
                break;

            case 'lpr_attendance_created':
                this.handleAttendanceCreated(data);
                break;

            case 'parking_event':
                this.handleParkingEvent(data);
                break;

            case 'lpr_error':
                this.handleLprError(data);
                break;

            case 'lpr_test_event':
                this.handleTestEvent(data);
                break;

            case 'lpr_broadcast':
                this.handleBroadcastMessage(data);
                break;

            default:
                console.log(`🚌 Неизвестен Bus event тип: ${type}`);
        }
    }

    handleLprEventDetected(data) {
        console.log('🚗 LPR събитие засечено:', data.plate);

        // Показваме processing overlay
        this.state.currentEvent = {
            plate: data.plate,
            time: new Date().toLocaleTimeString(),
            camera_name: data.camera_name,
            processing: true
        };

        this.state.overlayVisible = true;

        // Визуални ефекти за засичане
        this.triggerPulseEffect(document.querySelector('.event-overlay, .camera-container'));

        // Добавяме в списъка като processing
        this.addEventToList({
            ...data,
            processing_status: 'pending',
            access_granted: null
        });

        // Auto-hide след 15 секунди ако няма access result
        if (this.overlayTimeout) {
            clearTimeout(this.overlayTimeout);
        }

        this.overlayTimeout = setTimeout(() => {
            if (this.state.currentEvent && this.state.currentEvent.processing) {
                this.state.overlayVisible = false;
                this.state.currentEvent = null;
            }
        }, 15000);
    }

    handleAccessResult(data) {
        console.log('🔒 Access result получен:', data.plate, data.access_granted ? '✅' : '❌');

        // Визуални ефекти за резултат
        this.triggerFlashEffect(data.access_granted);
        this.showOverlayEffect(data.access_granted);

        // Обновяваме overlay с access информация
        if (this.state.currentEvent && this.state.currentEvent.plate === data.plate) {
            this.state.currentEvent = {
                ...this.state.currentEvent,
                processing: false,
                access_granted: data.access_granted,
                access_reason: data.access_reason,
                owner_name: data.owner_name,
                access_type: data.access_type
            };

            // Показваме по-дълго при отказан достъп
            if (this.overlayTimeout) {
                clearTimeout(this.overlayTimeout);
            }

            const displayTime = data.access_granted ? 5000 : 10000;
            this.overlayTimeout = setTimeout(() => {
                this.state.overlayVisible = false;
                this.state.currentEvent = null;
            }, displayTime);
        }

        // Обновяваме събитието в списъка
        this.updateEventInList(data);

        // Показваме нотификация
        this.showAccessNotification(data);
    }

    handleAttendanceCreated(data) {
        console.log('⏰ Attendance създаден:', data.employee_name, data.check_type);

        // Визуални ефекти за attendance
        this.triggerFlashEffect(true);

        if (this.notification) {
            this.notification.add(
                `⏰ ${data.check_type === 'check_in' ? 'Влизане' : 'Излизане'}: ${data.employee_name}`,
                { type: "info", title: "Отбелязване" }
            );
        } else {
            console.log(`⏰ ${data.check_type === 'check_in' ? 'Влизане' : 'Излизане'}: ${data.employee_name}`);
        }
    }

    handleParkingEvent(data) {
        console.log('🅿️ Parking събитие:', data.event_type, data.plate_number);

        // Визуални ефекти за паркинг
        this.triggerParkingEffect(data.event_type);

        if (data.event_type === 'entry') {
            this.triggerFlashEffect(true);
        } else if (data.event_type === 'exit') {
            this.triggerPulseEffect(document.querySelector('.lpr-panel, .events-section'));
        }

        const message = data.event_type === 'entry'
            ? `🅿️ Влизане в паркинг: ${data.partner_name} (${data.plate_number})`
            : `🅿️ Излизане от паркинг: ${data.partner_name} (${data.plate_number}) - Престой: ${data.duration_text}`;

        if (this.notification) {
            this.notification.add(message, {
                type: "info",
                title: "Паркинг"
            });
        } else {
            console.log(message);
        }
    }

    handleLprError(data) {
        console.error('❌ LPR грешка:', data.error);

        // Визуални ефекти за грешка
        this.triggerFlashEffect(false);
        this.triggerShakeEffect(document.querySelector('.lpr-panel, .events-section'));

        if (this.notification) {
            this.notification.add(
                `❌ Грешка при обработка на ${data.plate}: ${data.error}`,
                { type: "danger", title: "Системна грешка", sticky: true }
            );
        } else {
            console.error(`❌ Грешка при обработка на ${data.plate}: ${data.error}`);
        }
    }

    handleTestEvent(data) {
        console.log('🧪 Test bus събитие:', data);

        // Визуални ефекти за тест
        this.triggerPulseEffect(document.querySelector('.lpr-panel, .events-section'));

        if (this.notification) {
            this.notification.add(
                `🧪 Test: ${data.plate} - ${data.access_reason}`,
                { type: "info", title: "Bus Test" }
            );
        } else {
            console.log(`🧪 Test: ${data.plate} - ${data.access_reason}`);
        }
    }

    handleBroadcastMessage(data) {
        console.log('📢 Broadcast съобщение получено:', data.message);

        // Визуални ефекти за broadcast
        this.triggerPulseEffect(document.querySelector('.lpr-panel, .events-section'));

        const notificationType = {
            'info': 'info',
            'warning': 'warning',
            'error': 'danger',
            'success': 'success'
        }[data.message_type] || 'info';

        if (this.notification) {
            this.notification.add(
                `📢 ${data.message}`,
                {
                    type: notificationType,
                    title: `Broadcast от ${data.sender}`,
                    sticky: data.message_type === 'error'
                }
            );
        } else {
            console.log(`📢 ${data.message} (от ${data.sender})`);
        }
    }

    // =============== EVENT LIST MANAGEMENT ===============

    updateEventInList(accessData) {
        // Намираме и обновяваме събитието в списъка
        const eventIndex = this.state.events.findIndex(e =>
            e.id === accessData.event_id ||
            (e.plate === accessData.plate && Math.abs(new Date(e.timestamp) - new Date(accessData.event_time)) < 30000)
        );

        if (eventIndex >= 0) {
            this.state.events[eventIndex] = {
                ...this.state.events[eventIndex],
                id: accessData.event_id,
                access_granted: accessData.access_granted,
                access_reason: accessData.access_reason,
                owner_name: accessData.owner_name,
                processing_status: accessData.processing_status,
                timestamp: new Date(accessData.event_time)
            };
        }
    }

    addEventToList(eventData) {
        // Добавяме ново събитие в списъка
        const newEvent = {
            id: eventData.id || null,
            plate: eventData.plate,
            timestamp: new Date(eventData.timestamp || new Date()),
            camera_name: eventData.camera_name,
            processing_status: eventData.processing_status || 'pending',
            access_granted: eventData.access_granted,
            access_reason: eventData.access_reason || 'Обработване...',
            owner_name: eventData.owner_name || null
        };

        // Добавяме в началото на списъка
        this.state.events.unshift(newEvent);

        // Запазваме само последните 50 събития
        if (this.state.events.length > 50) {
            this.state.events = this.state.events.slice(0, 50);
        }

        // Добавяме визуален ефект за ново събитие
        setTimeout(() => {
            const newEventElement = document.querySelector('.event-item:first-child, .lpr-event:first-child');
            if (newEventElement) {
                newEventElement.classList.add('lpr-event-new');
                setTimeout(() => {
                    newEventElement.classList.remove('lpr-event-new');
                }, 3000);
            }
        }, 100);
    }

    // =============== UI NOTIFICATIONS ===============

    showAccessNotification(accessData) {
        const message = accessData.access_granted
            ? `✅ ДОСТЪП РАЗРЕШЕН: ${accessData.plate}${accessData.owner_name ? ` (${accessData.owner_name})` : ''}`
            : `❌ ДОСТЪП ОТКАЗАН: ${accessData.plate} - ${accessData.access_reason}`;

        const type = accessData.access_granted ? "success" : "danger";

        if (this.notification) {
            this.notification.add(message, {
                type: type,
                title: "LPR Контрол",
                sticky: !accessData.access_granted
            });
        } else {
            console.log(`${type.toUpperCase()}: ${message}`);
        }
    }

    // =============== BUS PUSH METHODS ===============

    async sendBusNotification(eventData) {
        try {
            console.log('📤 Изпращане на bus notification:', eventData);

            const response = await this.makeJsonRpcCall("/lpr_camera/send_bus_notification", {
                event_type: eventData.type,
                event_data: eventData.data,
                channel: 'lpr_camera_stream'
            });

            if (response.status === 'success') {
                console.log('✅ Bus notification изпратена успешно');
                return true;
            } else {
                console.error('❌ Грешка при изпращане на bus notification:', response.message);
                return false;
            }
        } catch (error) {
            console.error('❌ Изключение при изпращане на bus notification:', error);
            return false;
        }
    }

    async triggerLprEvent(plateNumber) {
        try {
            const response = await this.makeJsonRpcCall("/lpr_camera/trigger_lpr_event", {
                plate_number: plateNumber || 'TEST123',
                camera_name: this.state.camera?.name || 'Test Camera'
            });

            if (response.status === 'success') {
                if (this.notification) {
                    this.notification.add(
                        `📤 LPR събитие изпратено: ${response.event_data.plate}`,
                        { type: "success", title: "Bus Push" }
                    );
                } else {
                    console.log(`📤 LPR събитие изпратено: ${response.event_data.plate}`);
                }
            } else {
                if (this.notification) {
                    this.notification.add(
                        "❌ Неуспешно изпращане на LPR събитие",
                        { type: "danger", title: "Bus Error" }
                    );
                } else {
                    console.error("❌ Неуспешно изпращане на LPR събитие");
                }
            }

        } catch (error) {
            console.error('Грешка при trigger на LPR събитие:', error);
            if (this.notification) {
                this.notification.add(
                    `❌ Грешка: ${error.message}`,
                    { type: "danger", title: "Trigger Error" }
                );
            }
        }
    }

    async triggerAccessResult(plateNumber, accessGranted = true) {
        try {
            const response = await this.makeJsonRpcCall("/lpr_camera/trigger_access_result", {
                plate_number: plateNumber || 'TEST123',
                access_granted: accessGranted
            });

            if (response.status === 'success') {
                const resultText = accessGranted ? "разрешен" : "отказан";
                if (this.notification) {
                    this.notification.add(
                        `📤 Access result изпратен: ${response.access_data.plate} - ${resultText}`,
                        { type: "success", title: "Bus Push" }
                    );
                } else {
                    console.log(`📤 Access result изпратен: ${response.access_data.plate} - ${resultText}`);
                }
            }

        } catch (error) {
            console.error('Грешка при trigger на access result:', error);
        }
    }

    async triggerAttendanceEvent(employeeName) {
        try {
            // Изпращаме чрез sendBusNotification за да имаме повече контрол
            const eventData = {
                type: 'lpr_attendance_created',
                data: {
                    employee_name: employeeName || 'Тестов служител',
                    check_type: Math.random() > 0.5 ? 'check_in' : 'check_out',
                    check_time: new Date().toISOString(),
                    plate: 'EMP001',
                    camera_name: this.state.camera?.name || 'Test Camera'
                }
            };

            const success = await this.sendBusNotification(eventData);

            if (success && this.notification) {
                this.notification.add(
                    `📤 Attendance събитие изпратено: ${eventData.data.employee_name}`,
                    { type: "success", title: "Bus Push" }
                );
            }

        } catch (error) {
            console.error('Грешка при trigger на attendance събитие:', error);
        }
    }

    async triggerErrorEvent(errorMessage) {
        try {
            const eventData = {
                type: 'lpr_error',
                data: {
                    error: errorMessage || 'Тестова грешка при обработка',
                    plate: 'ERROR123',
                    camera_name: this.state.camera?.name || 'Test Camera',
                    timestamp: new Date().toISOString(),
                    error_code: 'TEST_ERROR'
                }
            };

            const success = await this.sendBusNotification(eventData);

            if (success && this.notification) {
                this.notification.add(
                    `📤 Error събитие изпратено: ${eventData.data.error}`,
                    { type: "warning", title: "Bus Push" }
                );
            }

        } catch (error) {
            console.error('Грешка при trigger на error събитие:', error);
        }
    }

    async broadcastToAllClients(message, messageType = 'info') {
        try {
            const response = await this.makeJsonRpcCall("/lpr_camera/broadcast", {
                message: message,
                message_type: messageType
            });

            if (response.status === 'success' && this.notification) {
                this.notification.add(
                    `📢 Broadcast съобщение изпратено: ${message}`,
                    { type: "info", title: "Broadcast" }
                );
            }

        } catch (error) {
            console.error('Грешка при broadcast съобщение:', error);
        }
    }

    async testBusNotification() {
        try {
            const response = await this.makeJsonRpcCall("/lpr_camera/test_bus");
            console.log('🧪 Test bus response:', response);

            if (response.status === 'success') {
                if (this.notification) {
                    this.notification.add("Test bus notification изпратена", { type: "info" });
                } else {
                    console.log("Test bus notification изпратена");
                }
            } else {
                const message = `Грешка при test: ${response.message}`;
                if (this.notification) {
                    this.notification.add(message, { type: "danger" });
                } else {
                    console.error(message);
                }
            }
        } catch (error) {
            console.error("Грешка при test bus:", error);
            if (this.notification) {
                this.notification.add("Грешка при изпращане на test", { type: "danger" });
            }
        }
    }

    // =============== EXISTING METHODS ===============

    async initializeKiosk() {
        try {
            // Зареждане на конфигурацията на камерата
            const response = await this.makeJsonRpcCall("/lpr_camera/config");

            if (response.status === 'success' && response.cameras.length > 0) {
                this.state.camera = response.cameras[0];
                this.loadRecentEvents();
            }
        } catch (error) {
            console.error("Грешка при инициализация на киоск:", error);
            if (this.notification) {
                this.notification.add("Грешка при зареждане на камерата", { type: "danger" });
            }
        }
    }

    async loadRecentEvents() {
        try {
            const response = await this.makeJsonRpcCall("/lpr_camera/recent_events", { limit: 20 });

            if (response.status === 'success') {
                this.state.events = response.events.map(event => ({
                    ...event,
                    timestamp: new Date(event.event_time),
                    plate: event.plate_number
                }));
                console.log(`📋 Заредени ${this.state.events.length} последни събития`);
            }
        } catch (error) {
            console.error("Грешка при зареждане на събития:", error);
        }
    }

    cleanup() {
        if (this.mqttListener) {
            this.mqttListener.disconnect();
        }

        if (this.eventUpdateInterval) {
            clearInterval(this.eventUpdateInterval);
        }

        if (this.overlayTimeout) {
            clearTimeout(this.overlayTimeout);
        }

        // Почистваме Bus listener
        if (this.busListener && this.bus) {
            this.bus.removeEventListener("lpr_camera_stream", this.busListener);
        }

        // Почистваме polling interval
        if (this.busPollingInterval) {
            clearInterval(this.busPollingInterval);
        }
    }

    // =============== GETTER METHODS ===============

    get connectionStatusClass() {
        return this.state.busConnected ? 'connected' : 'disconnected';
    }

    get connectionStatusText() {
        return this.state.busConnected ? '🟢 Bus Свързан' : '🔴 Bus Прекъснат';
    }

    get hasBusConnection() {
        return this.state.busConnected;
    }

    get canSendNotifications() {
        return this.state.busConnected && this.state.camera;
    }

    get eventsList() {
        return this.state.events;
    }

    get currentOverlayEvent() {
        return this.state.currentEvent;
    }

    get isOverlayVisible() {
        return this.state.overlayVisible;
    }
}

// Регистрираме компонента
registry.category("public_components").add("lpr_camera_kiosk", KioskCameraComponent);