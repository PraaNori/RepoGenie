#include <WiFi.h>
#include <HTTPClient.h>

const char* ssid = "SACHIN";
const char* password = "11112222";


const char* scriptURL = "https://script.google.com/macros/s/AKfycbwQ38YqgCD0IgVxm5ZBnlHbJxACTotZPev4ANChevgkc859qjf6b7VfUtnIDNNy9ldgDw/exec";

int mq135Pin = 32;

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connecting to WiFi...");
  }
  Serial.println("Connected to WiFi");
}

void loop() {
  float analogValue = analogRead(mq135Pin); 
  float voltage = analogValue * (3.3 / 4095.0);  
  float ppm = voltage * 100; 

  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(scriptURL);
    http.addHeader("Content-Type", "application/json");

    String payload = "{\"ppm\": " + String(ppm, 2) + "}";

    int httpCode = http.POST(payload);
    Serial.print("HTTP Response code: ");
    Serial.println(httpCode);
    http.end();
  } else {
    Serial.println("WiFi Disconnected");
  }

  delay(5000); 
}
