const { stringify } = require("csv-stringify/sync");
const yaml = require("js-yaml");
const { create } = require("xmlbuilder2");

function generateCsv(data) {
  const { headers, rows, delimiter = "," } = data;
  const records = [headers, ...rows];
  const output = stringify(records, { delimiter });
  return { buffer: Buffer.from(output, "utf-8"), ext: "csv", mime: "text/csv" };
}

function generateJson(data) {
  const output = JSON.stringify(data.content, null, 2);
  return { buffer: Buffer.from(output, "utf-8"), ext: "json", mime: "application/json" };
}

function generateXml(data) {
  const root = data.root || "root";
  const doc = create({ version: "1.0", encoding: "UTF-8" });
  const rootEl = doc.ele(root);
  buildXmlElement(rootEl, data.content);
  const output = doc.end({ prettyPrint: true });
  return { buffer: Buffer.from(output, "utf-8"), ext: "xml", mime: "application/xml" };
}

function buildXmlElement(parent, value) {
  if (value === null || value === undefined) {
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const child = parent.ele("item");
      if (typeof item === "object" && item !== null) {
        buildXmlElement(child, item);
      } else {
        child.txt(String(item));
      }
    }
  } else if (typeof value === "object") {
    for (const [key, val] of Object.entries(value)) {
      const child = parent.ele(key);
      if (typeof val === "object" && val !== null) {
        buildXmlElement(child, val);
      } else {
        child.txt(String(val ?? ""));
      }
    }
  } else {
    parent.txt(String(value));
  }
}

function generateYaml(data) {
  const output = yaml.dump(data.content, { lineWidth: 120, noRefs: true });
  return { buffer: Buffer.from(output, "utf-8"), ext: "yaml", mime: "text/yaml" };
}

function generateMarkdown(data) {
  return { buffer: Buffer.from(data.content, "utf-8"), ext: "md", mime: "text/markdown" };
}

function generateTxt(data) {
  return { buffer: Buffer.from(data.content, "utf-8"), ext: "txt", mime: "text/plain" };
}

module.exports = { generateCsv, generateJson, generateXml, generateYaml, generateMarkdown, generateTxt };
