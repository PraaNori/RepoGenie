CREATE OR REPLACE TABLE iot_data.sensor_readings (
  Timestamp TIMESTAMP,
  MQ_135_Air_Quality_Sensorppm FLOAT64
);

CREATE OR REPLACE TABLE iot_data.training_data AS
SELECT * FROM iot_data.sensor_readings LIMIT 7000;

CREATE OR REPLACE TABLE iot_data.realtime_data AS
SELECT * FROM iot_data.sensor_readings OFFSET 7000;

CREATE OR REPLACE TABLE iot_data.anomalies_detected (
  Timestamp TIMESTAMP,
  ppm FLOAT64,
  is_anomaly BOOL
);