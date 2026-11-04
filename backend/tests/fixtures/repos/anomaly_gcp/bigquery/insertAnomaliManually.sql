INSERT INTO iot_data.realtime_data (Timestamp, PPM)
VALUES (CURRENT_TIMESTAMP(), 10000); -- very high value to force anomaly
