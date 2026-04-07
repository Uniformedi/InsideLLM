const docx = require("docx");

const { Document, Packer, Paragraph, TextRun, HeadingLevel, Footer, AlignmentType, PageNumber } = docx;

async function generateDocx(data) {
  const { title = "", sections = [] } = data;

  const children = [];

  if (title) {
    children.push(
      new Paragraph({
        text: title,
        heading: HeadingLevel.TITLE,
        spacing: { after: 300 },
      })
    );
  }

  for (const section of sections) {
    if (section.heading) {
      children.push(
        new Paragraph({
          text: section.heading,
          heading: HeadingLevel.HEADING_1,
          spacing: { before: 240, after: 120 },
        })
      );
    }

    for (const para of section.paragraphs) {
      children.push(
        new Paragraph({
          children: [new TextRun({ text: para })],
          spacing: { after: 120 },
        })
      );
    }
  }

  const doc = new Document({
    sections: [
      {
        properties: {},
        children,
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [new TextRun({ children: [PageNumber.CURRENT] })],
              }),
            ],
          }),
        },
      },
    ],
  });

  const buffer = await Packer.toBuffer(doc);
  return {
    buffer,
    ext: "docx",
    mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  };
}

module.exports = { generateDocx };
