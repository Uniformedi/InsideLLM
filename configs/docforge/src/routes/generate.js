const express = require("express");
const { validateGenerate } = require("../middleware/validation");
const { generateDocx } = require("../generators/docx");
const { generateXlsx } = require("../generators/xlsx");
const { generatePptx } = require("../generators/pptx");
const { generatePdf } = require("../generators/pdf");
const { generateCsv, generateJson, generateXml, generateYaml, generateMarkdown, generateTxt } = require("../generators/text");

const router = express.Router();

const generators = {
  docx: generateDocx,
  xlsx: generateXlsx,
  pptx: generatePptx,
  pdf: generatePdf,
  csv: (data) => generateCsv(data),
  json: (data) => generateJson(data),
  xml: (data) => generateXml(data),
  yaml: (data) => generateYaml(data),
  markdown: (data) => generateMarkdown(data),
  txt: (data) => generateTxt(data),
};

router.post("/", validateGenerate, async (req, res, next) => {
  try {
    const { format, data, filename } = req.body;
    const generator = generators[format];
    const result = await generator(data);
    const outputFilename = filename || `document.${result.ext}`;

    res.set({
      "Content-Type": result.mime,
      "Content-Disposition": `attachment; filename="${outputFilename}"`,
      "Content-Length": result.buffer.length,
    });
    res.send(result.buffer);
  } catch (err) {
    next(err);
  }
});

module.exports = router;
