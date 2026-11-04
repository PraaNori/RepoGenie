SELECT *
FROM ML.FORECAST(MODEL iot_data.anomaly_model,
  STRUCT(1 AS horizon, 0.8 AS confidence_level))
ORDER BY forecast_timestamp DESC;