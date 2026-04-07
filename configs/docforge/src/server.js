const express = require("express");
const helmet = require("helmet");
const rateLimit = require("express-rate-limit");
const morgan = require("morgan");
const path = require("path");
const fs = require("fs");

const generateRouter = require("./routes/generate");
const convertRouter = require("./routes/convert");
const formatsRouter = require("./routes/formats");
const { errorHandler } = require("./middleware/error-handler");

const app = express();
const PORT = process.env.PORT || 3000;
const TEMP_DIR = process.env.TEMP_DIR || path.join(__dirname, "..", "data", "temp");

fs.mkdirSync(TEMP_DIR, { recursive: true });

app.use(helmet());
app.use(morgan("short"));
app.use(
  rateLimit({
    windowMs: 60 * 1000,
    max: 100,
    standardHeaders: true,
    legacyHeaders: false,
  })
);
app.use(express.json({ limit: "10mb" }));

app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "docforge", timestamp: new Date().toISOString() });
});

app.use("/api/generate", generateRouter);
app.use("/api/convert", convertRouter);
app.use("/api/formats", formatsRouter);

app.use(errorHandler);

// Temp file cleanup every 30 minutes
const CLEANUP_INTERVAL_MS = 30 * 60 * 1000;
const MAX_TEMP_AGE_MS = 60 * 60 * 1000;

function cleanTempFiles() {
  try {
    const files = fs.readdirSync(TEMP_DIR);
    const now = Date.now();
    for (const file of files) {
      const filePath = path.join(TEMP_DIR, file);
      const stat = fs.statSync(filePath);
      if (now - stat.mtimeMs > MAX_TEMP_AGE_MS) {
        fs.unlinkSync(filePath);
      }
    }
  } catch {
    // temp dir may not exist yet
  }
}

const cleanupTimer = setInterval(cleanTempFiles, CLEANUP_INTERVAL_MS);

process.on("SIGTERM", () => {
  clearInterval(cleanupTimer);
  cleanTempFiles();
  process.exit(0);
});

app.listen(PORT, () => {
  console.log(`DocForge listening on port ${PORT}`);
});
