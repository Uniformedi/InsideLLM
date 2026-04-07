const express = require("express");
const router = express.Router();

const FORMAT_INFO = {
  generation: {
    docx: { name: "Word Document", category: "office", ext: "docx" },
    xlsx: { name: "Excel Spreadsheet", category: "office", ext: "xlsx" },
    pptx: { name: "PowerPoint Presentation", category: "office", ext: "pptx" },
    pdf: { name: "PDF Document", category: "pdf", ext: "pdf" },
    csv: { name: "Comma-Separated Values", category: "text", ext: "csv" },
    json: { name: "JSON", category: "text", ext: "json" },
    xml: { name: "XML", category: "text", ext: "xml" },
    yaml: { name: "YAML", category: "text", ext: "yaml" },
    markdown: { name: "Markdown", category: "text", ext: "md" },
    txt: { name: "Plain Text", category: "text", ext: "txt" },
  },
  conversion: {
    input: ["docx", "xlsx", "pptx", "odt", "ods", "odp", "csv", "html", "rtf", "txt"],
    output: ["pdf", "docx", "xlsx", "pptx", "odt", "ods", "odp", "csv", "html", "rtf", "txt"],
    note: "Conversion between formats is handled by LibreOffice. Not all input/output combinations may be supported.",
  },
};

router.get("/", (_req, res) => {
  res.json(FORMAT_INFO);
});

module.exports = router;
