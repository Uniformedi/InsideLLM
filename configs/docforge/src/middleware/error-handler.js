function errorHandler(err, _req, res, _next) {
  const status = err.status || 500;
  const code = err.code || "INTERNAL_ERROR";
  const message = status === 500 ? "Internal server error" : err.message;

  if (status === 500) {
    console.error("Unhandled error:", err);
  }

  res.status(status).json({ error: message, code });
}

module.exports = { errorHandler };
