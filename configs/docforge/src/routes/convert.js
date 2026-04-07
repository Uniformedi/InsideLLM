const express = require("express");
const multer = require("multer");
const { convertFile } = require("../converters/libreoffice");

const router = express.Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 50 * 1024 * 1024 }, // 50MB
});

router.post("/", upload.single("file"), async (req, res, next) => {
  try {
    if (!req.file) {
      const err = new Error("No file uploaded. Send a file in the 'file' field.");
      err.status = 400;
      err.code = "MISSING_FILE";
      return next(err);
    }

    const targetFormat = req.query.targetFormat || req.body.targetFormat;
    if (!targetFormat) {
      const err = new Error("Missing targetFormat query parameter.");
      err.status = 400;
      err.code = "MISSING_FORMAT";
      return next(err);
    }

    const result = await convertFile(req.file.buffer, targetFormat);
    const originalName = req.file.originalname.replace(/\.[^.]+$/, "");
    const outputFilename = `${originalName}.${result.ext}`;

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
