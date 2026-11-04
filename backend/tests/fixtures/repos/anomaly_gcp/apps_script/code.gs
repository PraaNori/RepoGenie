function doPost(e) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const json = JSON.parse(e.postData.contents);

  const ppm = parseFloat(json.ppm);
  const time = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'HH:mm:ss');

  sheet.appendRow([ppm, time]);

  return ContentService.createTextOutput("Data saved");
}

function exportRealTimeData() {
  const projectId = 'vcc-project-final';
  const datasetId = 'iot_data';
  const tableId = 'realtime_data';

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("RealTimeData");
  const numRows = sheet.getLastRow() - 1; // excluding header

  if (numRows < 1) {
    Logger.log("No data to upload");
    return;
  }

  const data = sheet.getRange(2, 1, numRows, 2).getValues(); // Columns A (PPM), B (Timestamp)

  const rows = data.map(row => ({
    json: {
      Timestamp: Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss'),
      PPM: parseFloat(row[0])
    }
  }));

  const insertAllRequest = { rows: rows };

  // Use BigQuery.Tabledata (Capital T)
  BigQuery.Tabledata.insertAll(insertAllRequest, projectId, datasetId, tableId);

  Logger.log("Data uploaded to BigQuery");
}
