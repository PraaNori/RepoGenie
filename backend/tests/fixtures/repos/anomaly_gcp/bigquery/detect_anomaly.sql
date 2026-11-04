INSERT INTO iot_data.anomalies_detected (Timestamp, ppm, is_anomaly)
SELECT
  rt.Timestamp,
  rt.MQ_135_Air_Quality_Sensorppm,
  TRUE AS is_anomaly
FROM
  iot_data.realtime_data rt
JOIN
  ML.FORECAST(MODEL iot_data.anomaly_model, STRUCT(1 AS horizon, 0.8 AS confidence_level)) fc
ON TIMESTAMP_DIFF(rt.Timestamp, fc.forecast_timestamp, SECOND) <= 60
WHERE
  ABS(rt.MQ_135_Air_Quality_Sensorppm - fc.predicted_MQ_135_Air_Quality_Sensorppm) > 50;