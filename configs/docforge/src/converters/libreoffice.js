const libre = require("libreoffice-convert");
const { promisify } = require("util");

const convertAsync = promisify(libre.convert);

// Serialize LibreOffice invocations to avoid conflicts
let conversionQueue = Promise.resolve();

const CONVERSION_TIMEOUT_MS = 120_000;

const MIME_TYPES = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  odt: "application/vnd.oasis.opendocument.text",
  ods: "application/vnd.oasis.opendocument.spreadsheet",
  odp: "application/vnd.oasis.opendocument.presentation",
  csv: "text/csv",
  html: "text/html",
  rtf: "application/rtf",
  txt: "text/plain",
};

const SUPPORTED_OUTPUT = Object.keys(MIME_TYPES);

async function convertFile(inputBuffer, targetFormat) {
  if (!SUPPORTED_OUTPUT.includes(targetFormat)) {
    const err = new Error(`Unsupported target format: ${targetFormat}. Supported: ${SUPPORTED_OUTPUT.join(", ")}`);
    err.status = 400;
    err.code = "INVALID_FORMAT";
    throw err;
  }

  // Queue conversion to serialize LibreOffice calls
  const result = await enqueue(() => runConversion(inputBuffer, targetFormat));
  return result;
}

function enqueue(fn) {
  const pending = conversionQueue.then(fn, fn);
  conversionQueue = pending.catch(() => {});
  return pending;
}

async function runConversion(inputBuffer, targetFormat) {
  const ext = `.${targetFormat}`;

  const timeoutPromise = new Promise((_, reject) => {
    setTimeout(() => reject(new Error(`Conversion timed out after ${CONVERSION_TIMEOUT_MS / 1000}s`)), CONVERSION_TIMEOUT_MS);
  });

  const outputBuffer = await Promise.race([convertAsync(inputBuffer, ext, undefined), timeoutPromise]);

  return {
    buffer: Buffer.from(outputBuffer),
    ext: targetFormat,
    mime: MIME_TYPES[targetFormat] || "application/octet-stream",
  };
}

module.exports = { convertFile, SUPPORTED_OUTPUT, MIME_TYPES };
