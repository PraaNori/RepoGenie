CREATE OR REPLACE MODEL iot_data.anomaly_model
OPTIONS (
  MODEL_TYPE='ARIMA_PLUS',
  time_series_timestamp_col='Timestamp',
  time_series_data_col='MQ_135_Air_Quality_Sensorppm',
  horizon=1
) AS
SELECT
  Timestamp,
  MQ_135_Air_Quality_Sensorppm
FROM
  iot_data.training_data;