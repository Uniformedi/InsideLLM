const PDFDocument = require("pdfkit");
const { marked } = require("marked");

async function generatePdf(data) {
  const { title = "", content } = data;

  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({
      size: "LETTER",
      margins: { top: 72, bottom: 72, left: 72, right: 72 },
      info: { Title: title || "Document", Creator: "DocForge" },
    });

    const chunks = [];
    doc.on("data", (chunk) => chunks.push(chunk));
    doc.on("end", () =>
      resolve({
        buffer: Buffer.concat(chunks),
        ext: "pdf",
        mime: "application/pdf",
      })
    );
    doc.on("error", reject);

    if (title) {
      doc.fontSize(24).font("Helvetica-Bold").text(title, { align: "center" });
      doc.moveDown(1.5);
    }

    const tokens = marked.lexer(content);
    renderTokens(doc, tokens);

    // Page numbers
    const pages = doc.bufferedPageRange();
    for (let i = 0; i < pages.count; i++) {
      doc.switchToPage(i);
      doc.fontSize(9).font("Helvetica").text(`${i + 1}`, 0, doc.page.height - 50, {
        align: "center",
        width: doc.page.width,
      });
    }

    doc.end();
  });
}

function renderTokens(doc, tokens) {
  for (const token of tokens) {
    switch (token.type) {
      case "heading":
        renderHeading(doc, token);
        break;
      case "paragraph":
        doc.fontSize(11).font("Helvetica").text(stripInlineMarkdown(token.raw), { lineGap: 4 });
        doc.moveDown(0.5);
        break;
      case "list":
        renderList(doc, token);
        break;
      case "code":
        doc.fontSize(10).font("Courier").text(token.text, { lineGap: 2 });
        doc.moveDown(0.5);
        break;
      case "blockquote":
        doc.fontSize(11).font("Helvetica-Oblique").text(stripInlineMarkdown(token.raw.replace(/^>\s*/gm, "")), {
          indent: 20,
          lineGap: 4,
        });
        doc.moveDown(0.5);
        break;
      case "hr":
        doc.moveDown(0.5);
        doc
          .moveTo(72, doc.y)
          .lineTo(doc.page.width - 72, doc.y)
          .stroke("#CCCCCC");
        doc.moveDown(0.5);
        break;
      case "space":
        doc.moveDown(0.3);
        break;
      default:
        if (token.raw && token.raw.trim()) {
          doc.fontSize(11).font("Helvetica").text(stripInlineMarkdown(token.raw), { lineGap: 4 });
          doc.moveDown(0.5);
        }
        break;
    }
  }
}

function renderHeading(doc, token) {
  const sizes = { 1: 20, 2: 17, 3: 14, 4: 13, 5: 12, 6: 11 };
  const size = sizes[token.depth] || 11;
  doc.moveDown(0.3);
  doc.fontSize(size).font("Helvetica-Bold").text(stripInlineMarkdown(token.text));
  doc.moveDown(0.4);
}

function renderList(doc, token) {
  for (let i = 0; i < token.items.length; i++) {
    const item = token.items[i];
    const bullet = token.ordered ? `${i + 1}. ` : "\u2022 ";
    doc.fontSize(11).font("Helvetica").text(bullet + stripInlineMarkdown(item.text), { indent: 15, lineGap: 3 });
  }
  doc.moveDown(0.5);
}

function stripInlineMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/_(.+?)_/g, "$1")
    .replace(/`(.+?)`/g, "$1")
    .replace(/\[(.+?)\]\(.+?\)/g, "$1")
    .replace(/^#+\s*/gm, "")
    .replace(/^>\s*/gm, "")
    .trim();
}

module.exports = { generatePdf };
