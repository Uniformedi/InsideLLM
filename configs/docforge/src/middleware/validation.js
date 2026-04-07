const Joi = require("joi");

const MAX_CONTENT_LENGTH = 5 * 1024 * 1024; // 5MB text content

const sheetSchema = Joi.object({
  name: Joi.string().max(255).required(),
  headers: Joi.array().items(Joi.string().max(255)).min(1).required(),
  rows: Joi.array().items(Joi.array().items(Joi.alternatives().try(Joi.string(), Joi.number(), Joi.boolean(), Joi.allow(null)))).required(),
});

const sectionSchema = Joi.object({
  heading: Joi.string().max(500).allow(""),
  paragraphs: Joi.array().items(Joi.string().max(MAX_CONTENT_LENGTH)).min(1).required(),
});

const slideSchema = Joi.object({
  title: Joi.string().max(500).required(),
  content: Joi.string().max(MAX_CONTENT_LENGTH).allow(""),
  notes: Joi.string().max(MAX_CONTENT_LENGTH).allow(""),
});

const schemas = {
  docx: Joi.object({
    format: Joi.string().valid("docx").required(),
    data: Joi.object({
      title: Joi.string().max(500).allow(""),
      sections: Joi.array().items(sectionSchema).min(1).required(),
    }).required(),
    filename: Joi.string().max(255),
  }),

  xlsx: Joi.object({
    format: Joi.string().valid("xlsx").required(),
    data: Joi.object({
      sheets: Joi.array().items(sheetSchema).min(1).required(),
    }).required(),
    filename: Joi.string().max(255),
  }),

  pptx: Joi.object({
    format: Joi.string().valid("pptx").required(),
    data: Joi.object({
      title: Joi.string().max(500).allow(""),
      slides: Joi.array().items(slideSchema).min(1).required(),
    }).required(),
    filename: Joi.string().max(255),
  }),

  pdf: Joi.object({
    format: Joi.string().valid("pdf").required(),
    data: Joi.object({
      title: Joi.string().max(500).allow(""),
      content: Joi.string().max(MAX_CONTENT_LENGTH).required(),
    }).required(),
    filename: Joi.string().max(255),
  }),

  csv: Joi.object({
    format: Joi.string().valid("csv").required(),
    data: Joi.object({
      headers: Joi.array().items(Joi.string().max(255)).min(1).required(),
      rows: Joi.array().items(Joi.array().items(Joi.alternatives().try(Joi.string(), Joi.number(), Joi.boolean(), Joi.allow(null)))).required(),
      delimiter: Joi.string().max(1).default(","),
    }).required(),
    filename: Joi.string().max(255),
  }),

  json: Joi.object({
    format: Joi.string().valid("json").required(),
    data: Joi.object({
      content: Joi.any().required(),
    }).required(),
    filename: Joi.string().max(255),
  }),

  xml: Joi.object({
    format: Joi.string().valid("xml").required(),
    data: Joi.object({
      root: Joi.string().max(255).default("root"),
      content: Joi.any().required(),
    }).required(),
    filename: Joi.string().max(255),
  }),

  yaml: Joi.object({
    format: Joi.string().valid("yaml").required(),
    data: Joi.object({
      content: Joi.any().required(),
    }).required(),
    filename: Joi.string().max(255),
  }),

  markdown: Joi.object({
    format: Joi.string().valid("markdown").required(),
    data: Joi.object({
      content: Joi.string().max(MAX_CONTENT_LENGTH).required(),
    }).required(),
    filename: Joi.string().max(255),
  }),

  txt: Joi.object({
    format: Joi.string().valid("txt").required(),
    data: Joi.object({
      content: Joi.string().max(MAX_CONTENT_LENGTH).required(),
    }).required(),
    filename: Joi.string().max(255),
  }),
};

const SUPPORTED_FORMATS = Object.keys(schemas);

function validateGenerate(req, _res, next) {
  const { format } = req.body;

  if (!format || !SUPPORTED_FORMATS.includes(format)) {
    const err = new Error(`Unsupported format: ${format}. Supported: ${SUPPORTED_FORMATS.join(", ")}`);
    err.status = 400;
    err.code = "INVALID_FORMAT";
    return next(err);
  }

  const schema = schemas[format];
  const { error, value } = schema.validate(req.body, { stripUnknown: true });
  if (error) {
    const err = new Error(error.details[0].message);
    err.status = 400;
    err.code = "VALIDATION_ERROR";
    return next(err);
  }

  req.body = value;
  next();
}

module.exports = { validateGenerate, SUPPORTED_FORMATS };
