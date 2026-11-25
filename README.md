# IYAL: Women Safety Alert System

A low-cost wearable panic device (ESP32) that alerts a registered security guard on Telegram,
with the victim's location, within seconds. No SIM card or GSM module is needed.

## How it works
```
[ESP32 panic button] --WiFi/HTTPS--> [Cloud server (Flask + SQLite)] --> [Guard's Telegram]
                                          ^        |
[Phone companion page: live GPS] ---------+        +--> [Web dashboard: map + alert history]
```
1. The wearer presses the button. A 5-second window lets her cancel a false alarm.
2. The ESP32 sends the alert to the server with its device ID.
3. The server looks up the guard registered for that device in the database.
4. It attaches the freshest location (phone GPS if the companion page is open, else approximate internet location),
   converts it to an area name and sends a Telegram message plus a map pin to the guard.
5. Every alert is logged on the dashboard with a map.

## Hardware
ESP32 dev board, USB cable, phone hotspot (2.4 GHz). Uses the on-board BOOT button and LED.

## Run it
1. Create a Telegram bot with @BotFather and note the token. Send /start to the bot from the guard's account and get the chat ID.
2. Deploy `app.py` (for example on Render). Environment variables: `BOT_TOKEN`, `API_KEY`, `ADMIN_PIN`, `DEFAULT_CHAT_ID`.
3. Open `esp32_firmware/esp32_firmware.ino` in Arduino IDE, set WiFi, `SERVER_URL`, `API_KEY`, upload to ESP32.
4. On the wearer's phone, open `https://<your-app>/phone/DEV001` and allow location.

## Known limitations and future scope
- Without the companion page, location is only city-level. Planned: NEO-6M GPS module on the device.
- Planned: MPU6050 fall and violent-shake detection as an automatic trigger.
- Planned: SIM800L GSM fallback for areas without WiFi, guard acknowledgement and live tracking.
