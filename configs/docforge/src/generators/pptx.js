const PptxGenJS = require("pptxgenjs");

async function generatePptx(data) {
  const { title = "", slides = [] } = data;
  const pres = new PptxGenJS();
  pres.author = "DocForge";
  pres.title = title || "Presentation";

  // Title slide
  if (title) {
    const titleSlide = pres.addSlide();
    titleSlide.addText(title, {
      x: "10%",
      y: "35%",
      w: "80%",
      h: "20%",
      fontSize: 36,
      bold: true,
      align: "center",
      color: "1F2937",
    });
  }

  for (const slide of slides) {
    const s = pres.addSlide();

    // Slide title
    s.addText(slide.title, {
      x: "5%",
      y: "3%",
      w: "90%",
      h: "12%",
      fontSize: 24,
      bold: true,
      color: "1F2937",
    });

    // Slide content
    if (slide.content) {
      s.addText(slide.content, {
        x: "5%",
        y: "18%",
        w: "90%",
        h: "72%",
        fontSize: 16,
        color: "374151",
        valign: "top",
        wrap: true,
      });
    }

    // Speaker notes
    if (slide.notes) {
      s.addNotes(slide.notes);
    }
  }

  const buffer = await pres.write({ outputType: "nodebuffer" });
  return {
    buffer,
    ext: "pptx",
    mime: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  };
}

module.exports = { generatePptx };
