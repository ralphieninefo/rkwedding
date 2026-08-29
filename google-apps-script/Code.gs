/**
 * Installable edit trigger for deliberate venue outreach.
 * Script Properties required: WEBHOOK_URL and WEBHOOK_TOKEN.
 */
function onVenueReady(e) {
  const sheet = e.range.getSheet();
  if (sheet.getName() !== 'Venues' || e.range.getRow() < 2) return;

  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const index = Object.fromEntries(headers.map((name, i) => [String(name).trim(), i]));
  const required = ['Venue', 'Email', 'Status'];
  if (!required.every((name) => name in index)) {
    throw new Error('Venues sheet must include Venue, Email, and Status headers.');
  }

  const rowNumber = e.range.getRow();
  const row = sheet.getRange(rowNumber, 1, 1, headers.length).getValues()[0];
  if (String(row[index.Status]).trim() !== 'Ready') return;

  const venue = String(row[index.Venue]).trim();
  const email = String(row[index.Email]).trim();
  if (!venue || !email) {
    sheet.getRange(rowNumber, index.Status + 1).setValue('Needs info');
    return;
  }

  const properties = PropertiesService.getScriptProperties();
  const webhookUrl = properties.getProperty('WEBHOOK_URL');
  const webhookToken = properties.getProperty('WEBHOOK_TOKEN');
  if (!webhookUrl || !webhookToken) {
    throw new Error('Set WEBHOOK_URL and WEBHOOK_TOKEN in Script Properties.');
  }

  const lock = LockService.getDocumentLock();
  lock.waitLock(10000);
  try {
    sheet.getRange(rowNumber, index.Status + 1).setValue('Queueing');
    const response = UrlFetchApp.fetch(
      webhookUrl.replace(/\/$/, '') + '/events/sheets/venue?token=' + encodeURIComponent(webhookToken),
      {
        method: 'post',
        contentType: 'application/json',
        payload: JSON.stringify({row_number: rowNumber, venue: venue, email: email}),
        muteHttpExceptions: true,
      }
    );
    if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) {
      sheet.getRange(rowNumber, index.Status + 1).setValue('Outreach error');
      throw new Error('Webhook failed: ' + response.getContentText());
    }
  } finally {
    lock.releaseLock();
  }
}

/** Run once from Apps Script to install the editable-sheet trigger. */
function installVenueReadyTrigger() {
  const spreadsheet = SpreadsheetApp.getActive();
  ScriptApp.getProjectTriggers()
    .filter((trigger) => trigger.getHandlerFunction() === 'onVenueReady')
    .forEach((trigger) => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger('onVenueReady').forSpreadsheet(spreadsheet).onEdit().create();
}

/** Add missing tracker tabs and headers without overwriting existing content. */
function setupTrackerTabs() {
  const spreadsheet = SpreadsheetApp.getActive();
  const tabs = {
    Venues: ['Venue', 'Email', 'Status', 'Inquiry date', 'Last response', 'Quoted price', 'Currency', 'Gmail message ID', 'Gmail thread ID', 'Unresolved questions'],
    Quotes: ['Venue', 'Received at', 'Total price', 'Currency', 'Guest count', 'Price basis', 'Taxes included', 'Inclusions', 'Exclusions', 'PDF filenames', 'Gmail message ID', 'Gmail thread ID'],
    System: ['Key', 'Value'],
  };
  Object.entries(tabs).forEach(([name, headers]) => {
    const sheet = spreadsheet.getSheetByName(name) || spreadsheet.insertSheet(name);
    if (sheet.getLastRow() === 0) sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  });
}
