const ExcelJS = require("exceljs");

async function generateXlsx(data) {
  const { sheets } = data;
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "DocForge";
  workbook.created = new Date();

  for (const sheet of sheets) {
    const ws = workbook.addWorksheet(sheet.name);

    ws.columns = sheet.headers.map((header) => ({
      header,
      key: header,
      width: Math.max(header.length + 4, 12),
    }));

    // Bold header row
    const headerRow = ws.getRow(1);
    headerRow.font = { bold: true };
    headerRow.alignment = { horizontal: "center" };

    for (const row of sheet.rows) {
      const rowObj = {};
      for (let i = 0; i < sheet.headers.length; i++) {
        rowObj[sheet.headers[i]] = row[i] ?? "";
      }
      ws.addRow(rowObj);
    }

    // Auto-filter on header row
    if (sheet.rows.length > 0) {
      ws.autoFilter = {
        from: { row: 1, column: 1 },
        to: { row: 1, column: sheet.headers.length },
      };
    }
  }

  const buffer = await workbook.xlsx.writeBuffer();
  return {
    buffer: Buffer.from(buffer),
    ext: "xlsx",
    mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  };
}

module.exports = { generateXlsx };
