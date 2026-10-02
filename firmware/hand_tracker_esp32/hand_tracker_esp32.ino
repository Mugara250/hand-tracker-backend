// Hand Tracker body: polls GET /hand 5x/second and does exactly what the backend says.
//
//   servo.write(angle); then for LED i (0..4): pwm(pin[i], i < leds ? brightness : 0)
//
// The backend does all the thinking (smoothing, deadband, stale detection).
// If the backend can't be reached, the LEDs go off and the servo holds its angle.
//
// Board:   ESP32 Dev Module (Arduino core 3.x)
// Library: ESP32Servo by Kevin Harrington (Library Manager)
//
// Wiring:
//   LEDs   blue 2, yellow 5, red 4, green 18, green2 19  (each through a ~220 ohm resistor to GND)
//   Servo  signal (orange) -> GPIO 13, red -> VIN (5V), brown -> GND
//          GPIO 34 is INPUT-ONLY on the ESP32 and cannot drive a servo.

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ESP32Servo.h>

// ---------- Edit these ----------
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Laptop on the same WiFi:  "http://192.168.1.50:8000"   (run uvicorn with --host 0.0.0.0)
// Hosted on Render:         "https://hand-tracker-backend.onrender.com"
// Leave empty ("") to search the local network for the laptop on port 8000.
String BACKEND = "";
const uint16_t SEARCH_PORT = 8000;
// --------------------------------

const int SERVO_PIN = 13;
const int LED_PINS[5] = {2, 5, 4, 18, 19};  // blue, yellow, red, green, green2

const unsigned long POLL_MS = 200;          // 5x per second, same as tools/fake_esp32.py
const uint16_t HTTP_TIMEOUT_MS = 1500;
const int FAILS_BEFORE_SEARCH = 15;         // ~3 s of errors -> look for the laptop again

Servo servo;
int lastAngle = -1;
int fails = 0;
bool searched = false;  // true when BACKEND came from the network search

// Find "key": in the JSON and read the integer after it (the snapshot is flat and small).
int readInt(const String& body, const char* key) {
  String tag = String("\"") + key + "\":";
  int at = body.indexOf(tag);
  if (at < 0) return 0;
  return body.substring(at + tag.length()).toInt();
}

void setLeds(int leds, int brightness) {
  for (int i = 0; i < 5; i++) {
    analogWrite(LED_PINS[i], i < leds ? brightness : 0);
  }
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("WiFi: connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int blink = 0;
  while (WiFi.status() != WL_CONNECTED) {
    analogWrite(LED_PINS[0], (blink++ % 2) ? 255 : 0);  // blue blinks while connecting
    Serial.print(".");
    delay(250);
  }
  analogWrite(LED_PINS[0], 0);
  Serial.printf("\nWiFi: connected, my IP is %s\n", WiFi.localIP().toString().c_str());
}

// GET url; returns the HTTP code (negative = no connection) and fills body on 200.
int httpGet(const String& url, String& body, uint16_t timeoutMs) {
  HTTPClient http;
  WiFiClient plain;
  WiFiClientSecure secure;
  bool ok;
  if (url.startsWith("https://")) {
    secure.setInsecure();  // skip certificate checks; fine for a demo
    ok = http.begin(secure, url);
  } else {
    ok = http.begin(plain, url);
  }
  if (!ok) return -1;
  http.setTimeout(timeoutMs);
  http.setConnectTimeout(timeoutMs);
  int code = http.GET();
  if (code == 200) body = http.getString();
  http.end();
  return code;
}

// Ask every address on our /24 subnet for /health until one says "hand-tracker".
bool searchForBackend() {
  IPAddress me = WiFi.localIP();
  Serial.printf("Search: looking for the backend on %d.%d.%d.x:%u\n", me[0], me[1], me[2], SEARCH_PORT);
  for (int host = 1; host < 255; host++) {
    if (host == me[3]) continue;
    analogWrite(LED_PINS[1], (host % 2) ? 255 : 0);  // yellow blinks while searching

    IPAddress ip(me[0], me[1], me[2], host);
    WiFiClient probe;
    if (!probe.connect(ip, SEARCH_PORT, 100)) continue;  // nobody listening, move on fast
    probe.stop();

    String url = "http://" + ip.toString() + ":" + SEARCH_PORT;
    String body;
    if (httpGet(url + "/health", body, 800) == 200 && body.indexOf("hand-tracker") >= 0) {
      BACKEND = url;
      analogWrite(LED_PINS[1], 0);
      Serial.printf("Search: found it at %s\n", BACKEND.c_str());
      return true;
    }
  }
  analogWrite(LED_PINS[1], 0);
  Serial.println("Search: not found. Is uvicorn running with --host 0.0.0.0 on port 8000?");
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(200);

  // Servo first so it gets its own 50 Hz PWM timer before the LEDs take theirs.
  servo.setPeriodHertz(50);
  servo.attach(SERVO_PIN, 500, 2400);  // SG90 range; narrow to 1000..2000 if it buzzes at the ends

  for (int i = 0; i < 5; i++) {
    pinMode(LED_PINS[i], OUTPUT);
    analogWrite(LED_PINS[i], 0);
  }

  connectWifi();
  if (BACKEND.length() == 0) {
    searched = true;
    while (!searchForBackend()) delay(2000);
  }
  if (BACKEND.endsWith("/")) BACKEND.remove(BACKEND.length() - 1);
  Serial.printf("Polling %s/hand\n", BACKEND.c_str());
}

void loop() {
  static unsigned long lastPoll = 0;
  if (millis() - lastPoll < POLL_MS) return;
  lastPoll = millis();

  if (WiFi.status() != WL_CONNECTED) {
    setLeds(0, 0);
    connectWifi();
    return;
  }

  String body;
  int code = httpGet(BACKEND + "/hand", body, HTTP_TIMEOUT_MS);

  if (code != 200) {
    // Backend down or unreachable: LEDs off, servo holds where it is.
    setLeds(0, 0);
    Serial.printf("backend error %d\n", code);
    if (++fails >= FAILS_BEFORE_SEARCH && searched) {
      fails = 0;
      searchForBackend();  // the laptop may have a new IP
    }
    return;
  }
  fails = 0;

  int angle      = constrain(readInt(body, "angle"), 0, 180);
  int leds       = constrain(readInt(body, "leds"), 0, 5);
  int brightness = constrain(readInt(body, "brightness"), 0, 255);

  if (angle != lastAngle) {
    servo.write(angle);
    lastAngle = angle;
  }
  setLeds(leds, brightness);

  static String shown;
  String now = String(angle) + "/" + leds + "/" + brightness;
  if (now != shown) {
    Serial.printf("servo %3d  leds %d  pwm %3d\n", angle, leds, brightness);
    shown = now;
  }
}
