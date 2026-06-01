// =============================================================
// AURORA IoT FIRMWARE — ESP32-S3-DevKitC-1 (N16R8)
// =============================================================
// Components: OV3660 Camera + HC-SR04 Ultrasonic + MQTT (HiveMQ)
// Architecture: 
//   - Core 1 (loop):  WiFi, MQTT, Sensor, Actuator, WebSocket
//   - WebSocket pushes JPEG frames to server via Cloudflare Tunnel
//   - Smart LED Indicator (Idle→Pending→Success/Error)
// =============================================================

#include <Arduino.h>
#include <WiFi.h>
#include <AsyncMqttClient.h>
#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include "esp_camera.h"

#if __has_include("config.h")
  #include "config.h"
#else
  #error "Missing config.h. Copy src/config.example.h to src/config.h and fill in your local settings."
#endif

// =============================================================
// 🔧 USER CONFIGURATION — EDIT THESE VALUES
// =============================================================
// Local values live in src/config.h, which is intentionally gitignored.
// Start from src/config.example.h or run python setup.py from the repo root.


// =============================================================
// 📌 PINS (HC-SR04 + LEDs + Buzzer)
// =============================================================
#define TRIG_PIN 1
#define ECHO_PIN 2

#define LED_GREEN_PIN  38
#define LED_YELLOW_PIN 39
#define LED_RED_PIN    40
#define BUZZER_PIN     41   // Active-HIGH: HIGH = sound, LOW = silent

// =============================================================
// ⏱️ TIMING CONSTANTS
// =============================================================
const unsigned long SENSOR_INTERVAL   = 500;    // Publish distance every 500ms
const unsigned long STATUS_INTERVAL   = 10000;  // Heartbeat every 10s
const float DISTANCE_THRESHOLD        = 150.0;  // cm — trigger high-res & PENDING state
const unsigned long HOLD_DURATION     = 60000;  // Stay high-res for 60s after last detection
const unsigned long FRAME_INTERVAL    = 42;     // 24 FPS (~42ms between frames)

// =============================================================
// 📷 OV3660 CAMERA PIN DEFINITIONS (Freenove ESP32-S3 Standard)
// =============================================================
#define PWDN_GPIO_NUM  -1   // Not connected on most DevKitC boards
#define RESET_GPIO_NUM -1   // Not connected (software reset used)
#define XCLK_GPIO_NUM  15
#define SIOD_GPIO_NUM  4    // I2C SDA
#define SIOC_GPIO_NUM  5    // I2C SCL
#define Y9_GPIO_NUM    16   // D7
#define Y8_GPIO_NUM    17   // D6
#define Y7_GPIO_NUM    18   // D5
#define Y6_GPIO_NUM    12   // D4
#define Y5_GPIO_NUM    10   // D3
#define Y4_GPIO_NUM    8    // D2
#define Y3_GPIO_NUM    9    // D1
#define Y2_GPIO_NUM    11   // D0
#define VSYNC_GPIO_NUM 6
#define HREF_GPIO_NUM  7
#define PCLK_GPIO_NUM  13

// =============================================================
// 🌐 WEBSOCKET CONFIGURATION — Direct Local Connection
// =============================================================
// =============================================================
// 🚥 STATE MACHINE (Smart LED Indicator)
// =============================================================
enum SystemState {
    STATE_IDLE,      // Red LED ON        — standby, no person nearby
    STATE_PENDING,   // Yellow LED ON     — person detected, scanning
    STATE_SUCCESS,   // Green LED ON 2s   — face recognized
    STATE_ERROR      // Red LED blink 3x  — unknown face / error
};

SystemState systemState = STATE_IDLE;
unsigned long ledTimer = 0;
int blinkCount = 0;
bool blinkIsOn = false;

// =============================================================
// GLOBAL STATE
// =============================================================
AsyncMqttClient mqttClient;
TimerHandle_t mqttReconnectTimer;
TimerHandle_t wifiReconnectTimer;

WebSocketsClient wsClient;
bool wsConnected = false;
bool wsInitialized = false;
unsigned long lastFrameSend = 0;

unsigned long lastSensorPublish = 0;
unsigned long lastStatusPublish = 0;
unsigned long lastTriggerTime   = 0;

float currentDistance = -1;
bool highResActive = false;

// =============================================================
// LED HANDLER (Non-Blocking State Machine)
// =============================================================
void handleLEDs() {
    unsigned long now = millis();
    switch (systemState) {
        case STATE_IDLE:
            digitalWrite(LED_RED_PIN, HIGH);
            digitalWrite(LED_YELLOW_PIN, LOW);
            digitalWrite(LED_GREEN_PIN, LOW);
            break;
            
        case STATE_PENDING:
            digitalWrite(LED_RED_PIN, LOW);
            digitalWrite(LED_YELLOW_PIN, HIGH);
            digitalWrite(LED_GREEN_PIN, LOW);
            break;
            
        case STATE_SUCCESS:
            digitalWrite(LED_RED_PIN, LOW);
            digitalWrite(LED_YELLOW_PIN, LOW);
            digitalWrite(LED_GREEN_PIN, HIGH);
            if (now - ledTimer >= 2000) {
                systemState = STATE_IDLE;
            }
            break;
            
        case STATE_ERROR:
            digitalWrite(LED_YELLOW_PIN, LOW);
            digitalWrite(LED_GREEN_PIN, LOW);
            if (now - ledTimer >= 200) {
                ledTimer = now;
                blinkIsOn = !blinkIsOn;
                digitalWrite(LED_RED_PIN, blinkIsOn ? HIGH : LOW);
                if (!blinkIsOn) {
                    blinkCount++;
                    if (blinkCount >= 3) {
                        systemState = STATE_IDLE;
                    }
                }
            }
            break;
    }
}

// =============================================================
// FORWARD DECLARATIONS
// =============================================================
void connectToWifi();
void connectToMqtt();
void onWifiEvent(WiFiEvent_t event);
void onMqttConnect(bool sessionPresent);
void onMqttDisconnect(AsyncMqttClientDisconnectReason reason);
void onMqttMessage(char* topic, char* payload,
                   AsyncMqttClientMessageProperties properties,
                   size_t len, size_t index, size_t total);
float readUltrasonic();
bool tryCamera(int xclk_mhz);
bool initCamera();
void initWebSocket();
void onWebSocketEvent(WStype_t type, uint8_t *payload, size_t length);
void setResolution(framesize_t size);
void publishSensorData();
void publishStatus();

// =============================================================
// WiFi CONNECTION
// =============================================================
void connectToWifi() {
    if (WiFi.status() == WL_CONNECTED) return;  // Don't disrupt existing connection
    Serial.println("[WiFi] Connecting...");
    WiFi.begin(WIFI_SSID, WIFI_PASS);
}

void onWifiEvent(WiFiEvent_t event) {
    switch (event) {
        case ARDUINO_EVENT_WIFI_STA_GOT_IP:
            Serial.printf("[WiFi] ✓ Connected! IP: %s\n", WiFi.localIP().toString().c_str());
            Serial.printf("[WiFi] Signal: %d dBm\n", WiFi.RSSI());
            connectToMqtt();
            // Initialize WebSocket after WiFi is confirmed (SSL needs network)
            if (!wsInitialized) {
                Serial.printf("[DEBUG] Free heap before WS init: %d bytes\n", ESP.getFreeHeap());
                initWebSocket();
                wsInitialized = true;
            }
            break;
        case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
            Serial.println("[WiFi] ✗ Disconnected. Reconnecting in 2s...");
            xTimerStop(mqttReconnectTimer, 0);
            xTimerStart(wifiReconnectTimer, 0);
            break;
        default:
            break;
    }
}

// =============================================================
// MQTT CONNECTION & HANDLER
// =============================================================
void connectToMqtt() {
    Serial.printf("[MQTT] Connecting to %s:%d ...\n", MQTT_HOST, MQTT_PORT);
    mqttClient.connect();
}

void onMqttConnect(bool sessionPresent) {
    Serial.println("[MQTT] ✓ Connected to HiveMQ broker!");
    mqttClient.subscribe(TOPIC_COMMAND, 1);
    Serial.printf("[MQTT] ✓ Subscribed to: %s\n", TOPIC_COMMAND);
}

void onMqttDisconnect(AsyncMqttClientDisconnectReason reason) {
    Serial.printf("[MQTT] ✗ Disconnected (reason: %d). ", (int)reason);
    if (WiFi.isConnected()) {
        Serial.println("Reconnecting in 5s...");
        xTimerStart(mqttReconnectTimer, 0);
    } else {
        Serial.println("WiFi down — waiting for WiFi first.");
    }
}

void onMqttMessage(char* topic, char* payload,
                   AsyncMqttClientMessageProperties properties,
                   size_t len, size_t index, size_t total) {
    if (String(topic) != String(TOPIC_COMMAND)) return;

    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, payload, len);
    if (error) {
        Serial.printf("[MQTT] JSON parse error: %s\n", error.c_str());
        return;
    }

    const char* action = doc["action"] | "unknown";
    const char* name   = doc["name"]   | "";

    Serial.printf("[MQTT] ← Command: %s", action);
    if (strlen(name) > 0) Serial.printf(" (Name: %s)", name);
    Serial.println();

    // Action names MUST match server: "led_green" and "led_red"
    // (server/mqtt_client.py sends these exact strings)
    if (strcmp(action, "led_green") == 0) {
        systemState = STATE_SUCCESS;
        ledTimer = millis();
        // MM-FMD buzzer: short beep (active-HIGH)
        digitalWrite(BUZZER_PIN, HIGH);
        delay(100);
        digitalWrite(BUZZER_PIN, LOW);
        Serial.println("[ACT] ✅ Face recognized → Green LED");

    } else if (strcmp(action, "led_red") == 0) {
        systemState = STATE_ERROR;
        ledTimer = millis();
        blinkCount = 0;
        blinkIsOn = false;
        // No buzzer on unknown face — led_red fires every frame, would buzz nonstop
        Serial.println("[ACT] ❌ Unknown face → Red LED blink");

    } else if (strcmp(action, "buzzer") == 0) {
        digitalWrite(BUZZER_PIN, HIGH);
        delay(200);
        digitalWrite(BUZZER_PIN, LOW);
        Serial.println("[ACT] 🔊 Buzzer beep");
    }
}

// =============================================================
// HC-SR04 ULTRASONIC SENSOR
// =============================================================
float readUltrasonic() {
    // Trigger the sensor
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);

    long duration = pulseIn(ECHO_PIN, HIGH, 30000);  // 30ms timeout

    // Debug: log raw duration every 5s (static counter)
    static unsigned long lastRawLog = 0;
    if (millis() - lastRawLog >= 5000) {
        Serial.printf("[SENSOR-DBG] Echo pin=%d state=%d | duration=%ld us",
            ECHO_PIN, digitalRead(ECHO_PIN), duration);
        if (duration > 0) {
            float d = (duration * 0.0343f) / 2.0f;
            Serial.printf(" | dist=%.1f cm", d);
        } else {
            Serial.print(" | NO PULSE");
        }
        Serial.println();
        lastRawLog = millis();
    }

    if (duration == 0) return -1;  // No echo received
    float dist = (duration * 0.0343f) / 2.0f;
    if (dist < 2.0f) return -1;   // HC-SR04 min range is 2cm; below = noise
    return dist;
}

// =============================================================
// OV3660 TIMING DIAGNOSTICS (from deep research report)
// =============================================================
// Reads actual sensor timing registers to calculate exposure in
// real milliseconds instead of guessing arbitrary aec_value numbers.
// PCLK assumption: 10 MHz (stock OV3660 JPEG driver path)

typedef struct {
    uint16_t hts;          // Horizontal Total Size (cols per line incl. blanking)
    uint16_t vts;          // Vertical Total Size (lines per frame incl. blanking)
    uint16_t aec_rows;     // Current exposure in row units
    uint16_t agc_gain_int; // Approximate integer gain
    double line_time_us;   // Time per line in microseconds
    double frame_ms;       // Frame period in ms
    double exposure_ms;    // Exposure time in ms
} ov3660_stats_t;

static ov3660_stats_t ov3660_read_stats(sensor_t *s, uint32_t pclk_hz) {
    ov3660_stats_t st = {};

    st.hts = (uint16_t) s->get_reg(s, 0x380C, 0xFFFF);   // HTS
    st.vts = (uint16_t) s->get_reg(s, 0x380E, 0xFFFF);   // VTS

    int e0 = s->get_reg(s, 0x3500, 0x0F);
    int e1 = s->get_reg(s, 0x3501, 0xFF);
    int e2 = (s->get_reg(s, 0x3502, 0xF0) >> 4);
    st.aec_rows = (uint16_t) ((e0 << 12) | (e1 << 4) | e2);

    int g0 = s->get_reg(s, 0x350A, 0x03);
    int g1 = s->get_reg(s, 0x350B, 0xFF);
    int gainv = (g0 << 8) | g1;
    st.agc_gain_int = (uint16_t) ((gainv + 1) >> 4);

    st.line_time_us = (double) st.hts * 1e6 / (double) pclk_hz;
    st.frame_ms     = (double) st.vts * st.line_time_us / 1000.0;
    st.exposure_ms  = (double) st.aec_rows * st.line_time_us / 1000.0;

    return st;
}

// Convert desired exposure in milliseconds to OV3660 row count
static int ov3660_rows_from_ms(sensor_t *s, uint32_t pclk_hz, double target_ms) {
    ov3660_stats_t st = ov3660_read_stats(s, pclk_hz);
    int rows = (int) ((target_ms * 1000.0) / st.line_time_us + 0.5);
    if (rows < 1) rows = 1;
    if (rows > st.vts) rows = st.vts;   // Clamp to frame period
    return rows;
}

// =============================================================
// CAMERA INITIALIZATION
// =============================================================
esp_err_t lastCamError = ESP_OK;

bool tryCamera(int xclk_mhz) {
    Serial.printf("[CAM] Trying with XCLK=%d MHz...\n", xclk_mhz);

    camera_config_t config = {};
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = Y2_GPIO_NUM;
    config.pin_d1       = Y3_GPIO_NUM;
    config.pin_d2       = Y4_GPIO_NUM;
    config.pin_d3       = Y5_GPIO_NUM;
    config.pin_d4       = Y6_GPIO_NUM;
    config.pin_d5       = Y7_GPIO_NUM;
    config.pin_d6       = Y8_GPIO_NUM;
    config.pin_d7       = Y9_GPIO_NUM;
    config.pin_xclk     = XCLK_GPIO_NUM;
    config.pin_pclk     = PCLK_GPIO_NUM;
    config.pin_vsync    = VSYNC_GPIO_NUM;
    config.pin_href     = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn     = PWDN_GPIO_NUM;
    config.pin_reset    = RESET_GPIO_NUM;
    config.xclk_freq_hz = xclk_mhz * 1000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.grab_mode    = CAMERA_GRAB_LATEST;    // Always use latest frame (lowest latency)
    config.fb_location  = CAMERA_FB_IN_PSRAM;
    config.frame_size   = FRAMESIZE_QVGA;  // Start idle; VGA when person detected by ultrasonic
    config.jpeg_quality = 15;              // Good balance: smaller files, faster transport
    config.fb_count     = 2;               // Continuous DMA mode for higher FPS

    // If PSRAM is available, use higher quality + double buffer
    if (psramFound()) {
        Serial.println("[CAM] ✓ PSRAM found — high quality mode");
        config.jpeg_quality = 10;
        config.fb_count     = 2;
        config.grab_mode    = CAMERA_GRAB_LATEST;
    } else {
        // No PSRAM — limit resolution and use DRAM
        Serial.println("[CAM] ✗ No PSRAM — using DRAM fallback");
        config.frame_size   = FRAMESIZE_QVGA;  // 320x240
        config.fb_location  = CAMERA_FB_IN_DRAM;
    }

    lastCamError = esp_camera_init(&config);
    if (lastCamError != ESP_OK) {
        Serial.printf("[CAM] JPEG init failed (0x%x), trying RGB565 to detect sensor...\n", lastCamError);
        esp_camera_deinit();
        delay(100);

        // Try RGB565 to detect what sensor this is
        config.pixel_format = PIXFORMAT_RGB565;
        config.frame_size   = FRAMESIZE_QVGA;
        config.fb_count     = 1;
        config.fb_location  = CAMERA_FB_IN_DRAM;
        lastCamError = esp_camera_init(&config);
        if (lastCamError == ESP_OK) {
            sensor_t *s = esp_camera_sensor_get();
            if (s != NULL) {
                Serial.printf("[CAM] Detected sensor PID: 0x%x\n", s->id.PID);
                Serial.printf("[CAM] Sensor name: %s\n", s->id.PID == 0x2640 ? "OV2640" :
                                                          s->id.PID == 0x3660 ? "OV3660" :
                                                          s->id.PID == 0x5640 ? "OV5640" : "Unknown");
            }
            // Now re-init with JPEG
            esp_camera_deinit();
            delay(100);
            config.pixel_format = PIXFORMAT_JPEG;
            if (psramFound()) {
                config.frame_size   = FRAMESIZE_QVGA;  // Start idle; VGA when triggered
                config.jpeg_quality = 10;
                config.fb_count     = 2;
                config.fb_location  = CAMERA_FB_IN_PSRAM;
                config.grab_mode    = CAMERA_GRAB_LATEST;
            }
            lastCamError = esp_camera_init(&config);
            if (lastCamError != ESP_OK) {
                Serial.printf("[CAM] ✗ JPEG re-init also failed: 0x%x\n", lastCamError);
                return false;
            }
        } else {
            Serial.printf("[CAM] ✗ RGB565 init also failed: 0x%x\n", lastCamError);
            Serial.println("[CAM] Common errors:");
            Serial.println("  0x105 = I2C timeout (bad SDA/SCL wiring)");
            Serial.println("  0x20001 = No camera detected (ribbon cable loose?)");
            Serial.println("  0x20003 = Frame buffer alloc failed (PSRAM issue)");
            return false;
        }
    }

    Serial.println("[CAM] ✓ Camera initialized successfully");

    sensor_t *s = esp_camera_sensor_get();
    if (s != NULL) {
        Serial.printf("[CAM] Sensor PID: 0x%x\n", s->id.PID);

        // --- Phase 1: Basic image orientation & white balance ---
        s->set_vflip(s, 1);
        s->set_hmirror(s, 0);
        s->set_whitebal(s, 1);    // Auto white balance ON
        s->set_awb_gain(s, 1);    // AWB gain ON
        s->set_wb_mode(s, 0);     // Auto WB mode
        s->set_bpc(s, 1);         // Black pixel correction
        s->set_wpc(s, 1);         // White pixel correction

        // --- Phase 2: Warmup with auto exposure (let AWB/AEC settle) ---
        Serial.print("[CAM] Warming up (auto exposure)");
        for (int i = 0; i < 30; i++) {
            camera_fb_t *fb = esp_camera_fb_get();
            if (fb) esp_camera_fb_return(fb);
            delay(20);
            if (i % 10 == 0) Serial.print(".");
        }
        Serial.println(" done");

        // --- Phase 3: Print what auto exposure chose (before override) ---
        const uint32_t PCLK_HZ = 10000000;  // Stock OV3660 JPEG driver = 10 MHz PCLK
        ov3660_stats_t auto_st = ov3660_read_stats(s, PCLK_HZ);
        Serial.println("[CAM] === AUTO EXPOSURE REPORT ===");
        Serial.printf("[CAM]   HTS=%u  VTS=%u\n", auto_st.hts, auto_st.vts);
        Serial.printf("[CAM]   Line time: %.1f µs\n", auto_st.line_time_us);
        Serial.printf("[CAM]   Frame period: %.1f ms (%.1f fps)\n", auto_st.frame_ms, 1000.0 / auto_st.frame_ms);
        Serial.printf("[CAM]   Auto exposure: %u rows = %.1f ms\n", auto_st.aec_rows, auto_st.exposure_ms);
        Serial.printf("[CAM]   Auto gain: %u\n", auto_st.agc_gain_int);

        // --- Phase 4: Anti-motion-blur tuning (from research report) ---
        // Step 1: Disable night mode (AEC2) — #1 cause of blur
        //   aec2 maps to register 0x3A00[2] = night mode extension
        //   When ON, sensor extends frame period in low light → horrible blur
        s->set_aec2(s, 0);
        Serial.println("[CAM] ✓ Night mode (AEC2) DISABLED");

        // Step 2: Switch BOTH AEC and AGC to manual (report says pair them)
        s->set_exposure_ctrl(s, 0);   // Manual exposure
        s->set_gain_ctrl(s, 0);       // Manual gain
        Serial.println("[CAM] ✓ Manual exposure + gain mode");

        // Step 3: Set exposure target (short enough to freeze motion)
        //   6ms = research report default (too dark indoors)
        //   12ms/16ms = still dark, 20ms = 1/50s (bright, slight blur on fast motion)
        double target_exposure_ms = 20.0;
        int rows = ov3660_rows_from_ms(s, PCLK_HZ, target_exposure_ms);
        s->set_aec_value(s, rows);
        Serial.printf("[CAM] ✓ Exposure set: %.1f ms target → %d rows\n", target_exposure_ms, rows);

        // Step 4: Set moderate gain (8 out of 0-64 range)
        //   Higher gain = brighter but noisier. Add light instead of cranking gain.
        //   Gain does NOT reduce blur — only shorter exposure does.
        s->set_agc_gain(s, 32);
        Serial.println("[CAM] ✓ Gain set to 32 (high — expect some noise)");

        // Step 5: Set gain ceiling to prevent auto from going crazy if re-enabled
        s->set_gainceiling(s, (gainceiling_t)4);  // 16x max
        Serial.println("[CAM] ✓ Gain ceiling: 16x");

        // --- Phase 5: Verify final settings ---
        // Grab a few frames to let manual settings take effect
        for (int i = 0; i < 5; i++) {
            camera_fb_t *fb = esp_camera_fb_get();
            if (fb) esp_camera_fb_return(fb);
            delay(30);
        }

        ov3660_stats_t manual_st = ov3660_read_stats(s, PCLK_HZ);
        Serial.println("[CAM] === FINAL MANUAL SETTINGS ===");
        Serial.printf("[CAM]   Exposure: %u rows = %.1f ms (target was %.1f ms)\n",
                      manual_st.aec_rows, manual_st.exposure_ms, target_exposure_ms);
        Serial.printf("[CAM]   Gain: %u\n", manual_st.agc_gain_int);
        Serial.printf("[CAM]   Frame period: %.1f ms (%.1f fps)\n",
                      manual_st.frame_ms, 1000.0 / manual_st.frame_ms);

        if (manual_st.exposure_ms > 15.0) {
            Serial.println("[CAM] ⚠ WARNING: Exposure > 15ms — expect motion blur!");
            Serial.println("[CAM]   → Add more light to allow shorter exposure");
        } else {
            Serial.println("[CAM] ✓ Exposure looks good for motion freeze");
        }
    }

    // Test frame
    camera_fb_t *test = esp_camera_fb_get();
    if (test) {
        Serial.printf("[CAM] ✓ Test frame OK: %d bytes (%dx%d)\n",
            test->len, test->width, test->height);
        esp_camera_fb_return(test);
        return true;
    }
    Serial.println("[CAM] \u2717 Test frame failed!");
    return false;
}

bool initCamera() {
    // Research report: try 20 MHz first (official Arduino default), 10 MHz fallback
    if (tryCamera(20)) return true;
    Serial.println("[CAM] Retrying with 10MHz XCLK...");
    esp_camera_deinit();
    delay(500);
    if (tryCamera(10)) return true;
    
    Serial.println("[CAM] \u26a0 Camera init failed \u2014 continuing without camera.");
    return false;
}

// warmupCamera() is now integrated into tryCamera() above

// =============================================================
// ADAPTIVE RESOLUTION
// =============================================================
void setResolution(framesize_t size) {
    sensor_t *s = esp_camera_sensor_get();
    if (s == NULL) return;

    s->set_framesize(s, size);

    // Flush stale frames from the double-buffer pipeline
    // Without this, old-resolution frames cause stream freeze
    for (int i = 0; i < 3; i++) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (fb) esp_camera_fb_return(fb);
        delay(30);
    }

    Serial.printf("[CAM] Resolution switched to %dx%d\n",
        s->status.framesize <= FRAMESIZE_QVGA ? 320 :
        s->status.framesize == FRAMESIZE_CIF  ? 400 :
        s->status.framesize == FRAMESIZE_VGA  ? 640 : 0,
        s->status.framesize <= FRAMESIZE_QVGA ? 240 :
        s->status.framesize == FRAMESIZE_CIF  ? 296 :
        s->status.framesize == FRAMESIZE_VGA  ? 480 : 0);
}

// =============================================================
// WEBSOCKET CLIENT (Pushes JPEG frames to server via Cloudflare Tunnel)
// =============================================================
void onWebSocketEvent(WStype_t type, uint8_t *payload, size_t length) {
    switch (type) {
        case WStype_CONNECTED:
            Serial.println("[WS] ✓ Connected to server!");
            wsConnected = true;
            break;
        case WStype_DISCONNECTED:
            Serial.println("[WS] ✗ Disconnected from server");
            wsConnected = false;
            break;
        case WStype_ERROR:
            Serial.printf("[WS] ✗ Error: %s\n", payload ? (char*)payload : "unknown");
            wsConnected = false;
            break;
        case WStype_TEXT:
            Serial.printf("[WS] ← Text: %s\n", payload);
            break;
        default:
            break;
    }
}

void initWebSocket() {
    if (USE_SSL) {
        // Cloudflare Tunnel: SSL (library auto-sets insecure mode when no fingerprint given)
        wsClient.beginSSL(WS_HOST, WS_PORT, WS_PATH);
        Serial.printf("[WS] Target: wss://%s:%d%s\n", WS_HOST, WS_PORT, WS_PATH);
    } else {
        // bore/plain mode: no SSL needed
        wsClient.begin(WS_HOST, WS_PORT, WS_PATH);
        Serial.printf("[WS] Target: ws://%s:%d%s\n", WS_HOST, WS_PORT, WS_PATH);
    }

    wsClient.onEvent(onWebSocketEvent);
    wsClient.setReconnectInterval(3000);
    Serial.println("[WS] ✓ WebSocket client initialized");
}

// =============================================================
// MQTT PUBLISH HELPERS
// =============================================================
void publishSensorData() {
    if (!mqttClient.connected()) return;

    JsonDocument doc;
    doc["distance_cm"] = round(currentDistance * 10.0f) / 10.0f;

    char buffer[64];
    serializeJson(doc, buffer);
    mqttClient.publish(TOPIC_SENSOR, 0, false, buffer);
}

void publishStatus() {
    if (!mqttClient.connected()) return;

    JsonDocument doc;
    doc["state"]     = "online";
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["free_heap"] = ESP.getFreeHeap();
    doc["uptime_s"]  = millis() / 1000;

    char buffer[128];
    serializeJson(doc, buffer);
    mqttClient.publish(TOPIC_STATUS, 0, false, buffer);
}

// =============================================================
// SETUP
// =============================================================
void setup() {
    Serial.begin(115200);
    delay(3000);  // USB CDC needs extra time on ESP32-S3
    Serial.println("\n[DEBUG] >>> setup() reached <<<");
    Serial.flush();

    Serial.println();
    Serial.println("============================================");
    Serial.println("  AURORA IoT — ESP32-S3 Firmware v3.0");
    Serial.println("============================================");
    Serial.printf("  Board:  ESP32-S3-DevKitC-1 (N16R8)\n");
    Serial.printf("  Flash:  %d MB\n", ESP.getFlashChipSize() / 1024 / 1024);
    Serial.printf("  PSRAM:  %s (%d bytes)\n",
                  psramFound() ? "YES" : "NO", ESP.getPsramSize());
    Serial.printf("  Heap:   %d bytes free\n", ESP.getFreeHeap());
    Serial.println("============================================");

    // --- GPIO Setup ---
    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    pinMode(LED_GREEN_PIN, OUTPUT);
    pinMode(LED_YELLOW_PIN, OUTPUT);
    pinMode(LED_RED_PIN, OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);

    digitalWrite(TRIG_PIN, LOW);
    digitalWrite(LED_GREEN_PIN, LOW);
    digitalWrite(LED_YELLOW_PIN, LOW);
    digitalWrite(LED_RED_PIN, LOW);
    digitalWrite(BUZZER_PIN, LOW);   // MM-FMD active-HIGH: LOW = silent

    // --- AURORA Boot Sequence (LED + Buzzer synchronized) ---
    Serial.println("[BOOT] ♪ Running AURORA boot sequence...");

    // Phase 1: Quick triple beep (system check) — "dih-dih-dih"
    for (int i = 0; i < 3; i++) {
        digitalWrite(LED_RED_PIN, HIGH);
        digitalWrite(BUZZER_PIN, HIGH);
        delay(60);
        digitalWrite(BUZZER_PIN, LOW);
        digitalWrite(LED_RED_PIN, LOW);
        delay(80);
    }
    delay(150);

    // Phase 2: Double pulse (sensors online) — "dah-dah"
    for (int i = 0; i < 2; i++) {
        digitalWrite(LED_YELLOW_PIN, HIGH);
        digitalWrite(BUZZER_PIN, HIGH);
        delay(120);
        digitalWrite(BUZZER_PIN, LOW);
        digitalWrite(LED_YELLOW_PIN, LOW);
        delay(100);
    }
    delay(200);

    // Phase 3: Long confirm beep (system ready) — "daaaah"
    digitalWrite(LED_GREEN_PIN, HIGH);
    digitalWrite(BUZZER_PIN, HIGH);
    delay(300);
    digitalWrite(BUZZER_PIN, LOW);
    delay(80);

    // Phase 4: Final short chirp (AURORA online!) — "dit!"
    digitalWrite(BUZZER_PIN, HIGH);
    delay(50);
    digitalWrite(BUZZER_PIN, LOW);
    digitalWrite(LED_GREEN_PIN, LOW);

    Serial.println("[BOOT] ✓ Boot sequence complete");

    // --- Camera ---
    initCamera();

    // --- FreeRTOS Reconnect Timers ---
    mqttReconnectTimer = xTimerCreate(
        "mqttTimer", pdMS_TO_TICKS(5000), pdFALSE,
        (void*)0, [](TimerHandle_t t) { connectToMqtt(); }
    );
    wifiReconnectTimer = xTimerCreate(
        "wifiTimer", pdMS_TO_TICKS(2000), pdFALSE,
        (void*)0, [](TimerHandle_t t) { connectToWifi(); }
    );

    // --- MQTT Client Setup ---
    mqttClient.onConnect(onMqttConnect);
    mqttClient.onDisconnect(onMqttDisconnect);
    mqttClient.onMessage(onMqttMessage);
    mqttClient.setKeepAlive(60);
    mqttClient.setClientId("aurora-esp32s3");
    mqttClient.setServer(MQTT_HOST, MQTT_PORT);

    // --- WiFi ---
    WiFi.onEvent(onWifiEvent);
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);  // Disable WiFi power save — prevents frame drops
    connectToWifi();

    // Wait for WiFi (with timeout — don't hang forever)
    Serial.print("[WiFi] Waiting for connection");
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
        delay(500);
        Serial.print(".");
        attempts++;
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println();
        Serial.println("============================================");
        Serial.println("  🚀 AURORA IS READY!");
        Serial.printf("  📡 MQTT:   %s:%d\n", MQTT_HOST, MQTT_PORT);
        Serial.printf("  📷 Stream: wss://%s%s\n", WS_HOST, WS_PATH);
        Serial.printf("  📏 Sensor: GPIO %d (Trig) + GPIO %d (Echo)\n", TRIG_PIN, ECHO_PIN);
        Serial.printf("  💾 Free heap: %d bytes\n", ESP.getFreeHeap());
        Serial.println("============================================");
    } else {
        Serial.println("[WiFi] ✗ Failed to connect! Check SSID/password.");
        Serial.println("[WiFi] Will keep retrying in background...");
    }
}

// =============================================================
// MAIN LOOP
// =============================================================
void loop() {
    unsigned long now = millis();

    // 1. Network & LED maintenance (must run every iteration)
    wsClient.loop();
    handleLEDs();

    // 2. Send camera frame via WebSocket (rate-limited)
    if (wsConnected && (now - lastFrameSend >= FRAME_INTERVAL)) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (fb) {
            wsClient.sendBIN(fb->buf, fb->len);
            esp_camera_fb_return(fb);
            lastFrameSend = now;
        }
    }

    // 3. Read ultrasonic sensor & trigger adaptive resolution
    if (now - lastSensorPublish >= SENSOR_INTERVAL) {
        currentDistance = readUltrasonic();

        // Log distance every 5 seconds for debugging
        static unsigned long lastDistLog = 0;
        if (now - lastDistLog >= 5000) {
            if (currentDistance > 0) {
                Serial.printf("[SENSOR] Distance: %.1f cm %s\n", 
                    currentDistance,
                    currentDistance <= DISTANCE_THRESHOLD ? "(PERSON DETECTED)" : "");
            } else {
                Serial.println("[SENSOR] No echo (out of range or disconnected)");
            }
            lastDistLog = now;
        }

        if (currentDistance > 0) {
            publishSensorData();

            if (currentDistance <= DISTANCE_THRESHOLD) {
                if (!highResActive) {
                    Serial.printf("[SENSOR] Person at %.1f cm → VGA + PENDING\n", currentDistance);
                    setResolution(FRAMESIZE_VGA);
                    highResActive = true;
                    systemState = STATE_PENDING;  // Yellow LED ON
                }
                lastTriggerTime = now;
            }
        }
        lastSensorPublish = now;
    }

    // 4. Return to low-res after hold timer expires
    if (highResActive && (now - lastTriggerTime > HOLD_DURATION)) {
        Serial.println("[SENSOR] No activity → QVGA + IDLE");
        setResolution(FRAMESIZE_QVGA);
        highResActive = false;

        if (systemState != STATE_SUCCESS && systemState != STATE_ERROR) {
            systemState = STATE_IDLE;
        }
    }

    // 5. Publish status heartbeat
    if (now - lastStatusPublish >= STATUS_INTERVAL) {
        publishStatus();
        lastStatusPublish = now;
    }

    delay(1);  // Yield to avoid WDT reset
}
