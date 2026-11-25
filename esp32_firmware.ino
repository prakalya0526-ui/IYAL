// SafeAlert ESP32 firmware: BOOT button = panic button.
// Press once -> LED blinks for 5 s (press again to CANCEL a false alarm) -> alert is sent to the server.
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

const char* WIFI_SSID  = "YOUR_HOTSPOT";
const char* WIFI_PASS  = "YOUR_PASSWORD";
const char* SERVER_URL = "https://YOUR-APP.onrender.com/api/alert";
const char* API_KEY    = "demo-key";   // must match the API_KEY set on the server
const char* DEVICE_ID  = "DEV001";

#define BTN 0   // on-board BOOT button
#define LED 2   // on-board LED

unsigned long lastAlert = 0;

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nConnected. IP: " + WiFi.localIP().toString());
}

// 5-second window: blink LED, press BOOT again to cancel
bool confirmWindow() {
  while (digitalRead(BTN) == LOW) delay(10);          // wait for release of first press
  unsigned long t = millis();
  while (millis() - t < 5000) {
    digitalWrite(LED, (millis() / 150) % 2);
    if (digitalRead(BTN) == LOW) {
      digitalWrite(LED, LOW);
      Serial.println("Alert CANCELLED");
      while (digitalRead(BTN) == LOW) delay(10);
      return false;
    }
    delay(10);
  }
  return true;
}

void sendAlert(const char* reason) {
  WiFiClientSecure client;
  client.setInsecure();                               // fine for a demo
  HTTPClient https;
  https.setTimeout(30000);                            // free servers can take ~30 s to wake up
  https.begin(client, SERVER_URL);
  https.addHeader("Content-Type", "application/json");
  String body = "{\"device_id\":\"" + String(DEVICE_ID) + "\",\"key\":\"" + String(API_KEY) +
                "\",\"reason\":\"" + String(reason) + "\"}";
  int code = https.POST(body);
  Serial.printf("Server response: %d\n", code);
  Serial.println(https.getString());
  https.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN, INPUT_PULLUP);
  pinMode(LED, OUTPUT);
  connectWiFi();
  Serial.println("Ready. Press BOOT to raise an alert.");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (digitalRead(BTN) == LOW && millis() - lastAlert > 10000) {
    Serial.println("Button pressed. Press again within 5 s to cancel.");
    if (confirmWindow()) {
      digitalWrite(LED, HIGH);
      Serial.println("Sending alert...");
      sendAlert("panic button");
      lastAlert = millis();
      delay(2000);
      digitalWrite(LED, LOW);
    }
  }
  delay(50);
}
