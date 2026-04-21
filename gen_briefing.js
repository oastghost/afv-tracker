const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  LevelFormat, PageNumber, Header, Footer, PageBreak,
  UnderlineType
} = require('C:/Users/msude/AppData/Roaming/npm/node_modules/docx');
const fs = require('fs');

// ── Colour palette ──────────────────────────────────────────────────────────
const RED   = "CC1F36";
const DARK  = "1C1C1E";
const LGRAY = "F0F2F7";
const MGRAY = "C8CEDC";
const DGRAY = "5A6478";
const WHITE = "FFFFFF";
const BLACK = "000000";

// ── Helpers ─────────────────────────────────────────────────────────────────
const border = (color = MGRAY) => ({ style: BorderStyle.SINGLE, size: 1, color });
const noBorder = () => ({ style: BorderStyle.NONE, size: 0, color: WHITE });
const allBorders = (color = MGRAY) => ({ top: border(color), bottom: border(color), left: border(color), right: border(color) });
const noAllBorders = () => ({ top: noBorder(), bottom: noBorder(), left: noBorder(), right: noBorder() });

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 120 },
    children: [new TextRun({ text, font: "Arial", size: 36, bold: true, color: RED })]
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 80 },
    children: [new TextRun({ text, font: "Arial", size: 28, bold: true, color: DARK })]
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 60 },
    children: [new TextRun({ text, font: "Arial", size: 24, bold: true, color: DARK })]
  });
}

function body(text, opts = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 100 },
    children: [new TextRun({ text, font: "Arial", size: 22, color: BLACK, ...opts })]
  });
}

function bold(text) {
  return body(text, { bold: true });
}

function note(text) {
  return new Paragraph({
    spacing: { before: 40, after: 60 },
    children: [new TextRun({ text, font: "Arial", size: 20, color: DGRAY, italics: true })]
  });
}

function gap(size = 120) {
  return new Paragraph({ spacing: { before: size, after: 0 }, children: [] });
}

function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, font: "Arial", size: 22, color: BLACK })]
  });
}

function numbered(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "numbers", level },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, font: "Arial", size: 22, color: BLACK })]
  });
}

function divider() {
  return new Paragraph({
    spacing: { before: 200, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: MGRAY } },
    children: []
  });
}

// ── Coloured section label ───────────────────────────────────────────────────
function chapterLabel(text) {
  return new Paragraph({
    spacing: { before: 80, after: 40 },
    children: [new TextRun({
      text: text.toUpperCase(),
      font: "Arial",
      size: 18,
      bold: true,
      color: WHITE,
      highlight: undefined,
    })]
  });
}

// ── Table builders ──────────────────────────────────────────────────────────
function headerRow(cells, widths) {
  return new TableRow({
    tableHeader: true,
    children: cells.map((text, i) =>
      new TableCell({
        width: { size: widths[i], type: WidthType.DXA },
        shading: { fill: DARK, type: ShadingType.CLEAR },
        borders: allBorders(DARK),
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({
          children: [new TextRun({ text, font: "Arial", size: 20, bold: true, color: WHITE })]
        })]
      })
    )
  });
}

function dataRow(cells, widths, shade = WHITE) {
  return new TableRow({
    children: cells.map((text, i) =>
      new TableCell({
        width: { size: widths[i], type: WidthType.DXA },
        shading: { fill: shade, type: ShadingType.CLEAR },
        borders: allBorders(MGRAY),
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({
          children: [new TextRun({ text, font: "Arial", size: 20, color: BLACK })]
        })]
      })
    )
  });
}

function colourCell(text, hex, textColor = WHITE, width = 3120) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: { fill: hex, type: ShadingType.CLEAR },
    borders: allBorders(MGRAY),
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      children: [new TextRun({ text, font: "Arial", size: 20, color: textColor })]
    })]
  });
}

// Content width: A4 with 1" margins = 11906 - 2880 = 9026 DXA
const CW = 9026;

// ────────────────────────────────────────────────────────────────────────────
// DOCUMENT
// ────────────────────────────────────────────────────────────────────────────
const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2022",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }, {
          level: 1, format: LevelFormat.BULLET, text: "\u25E6",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 360 } } }
        }]
      },
      {
        reference: "numbers",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      }
    ]
  },
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: RED },
        paragraph: { spacing: { before: 360, after: 120 }, outlineLevel: 0 }
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: DARK },
        paragraph: { spacing: { before: 280, after: 80 }, outlineLevel: 1 }
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: DARK },
        paragraph: { spacing: { before: 200, after: 60 }, outlineLevel: 2 }
      }
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 }, // A4
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: MGRAY, space: 1 } },
          spacing: { after: 120 },
          children: [new TextRun({ text: "Africana Airways — Briefing UI/UX", font: "Arial", size: 18, color: DGRAY })]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: MGRAY, space: 1 } },
          spacing: { before: 120 },
          children: [
            new TextRun({ text: "Africana Virtual Airways  |  P\u00e1gina ", font: "Arial", size: 18, color: DGRAY }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: DGRAY }),
            new TextRun({ text: " de ", font: "Arial", size: 18, color: DGRAY }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Arial", size: 18, color: DGRAY })
          ]
        })]
      })
    },
    children: [

      // ── CAPA ─────────────────────────────────────────────────────────────
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 1440, after: 0 },
        children: [new TextRun({ text: "AFRICANA VIRTUAL AIRWAYS", font: "Arial", size: 52, bold: true, color: RED })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 120, after: 60 },
        children: [new TextRun({ text: "Briefing de Design UI/UX", font: "Arial", size: 36, color: DARK })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 60, after: 0 },
        children: [new TextRun({ text: "Fases 1 & 2  \u2014  Documenta\u00e7\u00e3o para Figma", font: "Arial", size: 24, color: DGRAY, italics: true })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 2880, after: 0 },
        children: [new TextRun({ text: "Abril 2026", font: "Arial", size: 22, color: DGRAY })]
      }),

      new Paragraph({ children: [new PageBreak()] }),

      // ── INTRO ─────────────────────────────────────────────────────────────
      h1("Introdu\u00e7\u00e3o"),
      body("Este documento cont\u00e9m as decis\u00f5es de design efectivamente implementadas no site da Africana Airways (projecto IADE_AFVsite), servindo de base para a documenta\u00e7\u00e3o formal de Fase 1 & 2, para os mockups em Figma e para o desenvolvimento final do site."),
      body("O site foi constru\u00eddo com HTML/CSS/JS vanilla e Leaflet.js para o mapa de rotas interactivo."),
      gap(),

      // ── CAP 5 ─────────────────────────────────────────────────────────────
      new Paragraph({ children: [new PageBreak()] }),
      h1("Cap\u00edtulo 5 \u2014 Arquitectura de Informa\u00e7\u00e3o"),
      body("O site est\u00e1 organizado em 8 p\u00e1ginas principais com a seguinte hierarquia:"),
      gap(80),

      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [1600, 2800, 4626],
        rows: [
          headerRow(["P\u00e1gina", "Ficheiro", "Descri\u00e7\u00e3o"], [1600, 2800, 4626]),
          dataRow(["Homepage",        "index.html",          "Hero, widget de pesquisa, destinos em destaque, CTA"], [1600, 2800, 4626], WHITE),
          dataRow(["Resultados",       "search-results.html", "Lista de voos com pre\u00e7os por classe (Econ\u00f3mica / Business / Primeira)"], [1600, 2800, 4626], LGRAY),
          dataRow(["Reserva",          "booking.html",        "Formul\u00e1rio de passageiros, mapa de assentos, pagamento, confirma\u00e7\u00e3o"], [1600, 2800, 4626], WHITE),
          dataRow(["Rotas",            "routes.html",         "Mapa interactivo (Leaflet.js) com filtro por hub"], [1600, 2800, 4626], LGRAY),
          dataRow(["Frota",            "fleet.html",          "Cards de aeronaves com filtros por categoria e modal de detalhe"], [1600, 2800, 4626], WHITE),
          dataRow(["Opera\u00e7\u00f5es Live",  "vatsim.html",         "Rastreio de voos VATSIM em tempo real"], [1600, 2800, 4626], LGRAY),
          dataRow(["Sobre N\u00f3s",    "about.html",          "Apresenta\u00e7\u00e3o da companhia"], [1600, 2800, 4626], WHITE),
          dataRow(["Backoffice",        "admin.html",          "Painel de administra\u00e7\u00e3o interno (voos, portas, pilotos)"], [1600, 2800, 4626], LGRAY),
        ]
      }),

      gap(200),
      h3("Hierarquia de navega\u00e7\u00e3o"),
      bullet("Homepage"),
      bullet("Pesquisa de voos \u2192 Resultados \u2192 Reserva \u2192 Confirma\u00e7\u00e3o", 1),
      bullet("Rotas"),
      bullet("Frota"),
      bullet("Opera\u00e7\u00f5es Live"),
      bullet("Sobre N\u00f3s"),
      bullet("Backoffice (acesso restrito)"),
      gap(100),
      note("P\u00e1ginas \"As Minhas Viagens\" e IFE n\u00e3o foram implementadas nesta fase \u2014 podem ser planeadas como Fase 3."),

      // ── CAP 6 ─────────────────────────────────────────────────────────────
      new Paragraph({ children: [new PageBreak()] }),
      h1("Cap\u00edtulo 6 \u2014 User Task Flow: Reserva de um Voo"),
      body("O fluxo principal de reserva percorre 5 p\u00e1ginas e 3 passos formais dentro da p\u00e1gina de reserva:"),
      gap(80),

      ...(() => {
        const steps = [
          ["1", "Homepage", "O utilizador acede ao site e visualiza o hero com o widget de pesquisa."],
          ["2", "Widget de Pesquisa", "Preenche: Origem, Destino, Data, N.\u00ba de passageiros, Classe. Clica em Pesquisar."],
          ["3", "Resultados (search-results.html)", "V\u00ea a lista de voos dispon\u00edveis. Cada card mostra hora, dura\u00e7\u00e3o, rota e pre\u00e7o por classe (Econ\u00f3mica / Business / Primeira). Selecciona a classe desejada."],
          ["4", "Reserva \u2014 Passo 1", "Dados dos passageiros: formul\u00e1rio em grelha de 2 colunas com nome, email, passaporte, etc."],
          ["5", "Reserva \u2014 Passo 2", "Selec\u00e7\u00e3o do assento: mapa interactivo com 7 colunas. Cores: branco (livre), vermelho (seleccionado), cinzento (ocupado). Zonas: Primeira Classe, Business, Econ\u00f3mica."],
          ["6", "Reserva \u2014 Passo 3", "Resumo e pagamento. Sidebar lateral fixo com o sum\u00e1rio da reserva."],
          ["7", "Confirma\u00e7\u00e3o", "Card centrado com \u00edcone verde, c\u00f3digo de reserva em monospace com borda tracejada."],
        ];
        return [
          new Table({
            width: { size: CW, type: WidthType.DXA },
            columnWidths: [600, 2600, 5826],
            rows: [
              headerRow(["#", "Ecr\u00e3", "Ac\u00e7\u00e3o / Conte\u00fado"], [600, 2600, 5826]),
              ...steps.map(([n, page, action], i) =>
                dataRow([n, page, action], [600, 2600, 5826], i % 2 === 0 ? WHITE : LGRAY)
              )
            ]
          }),
          gap(200),
          h3("Barra de progresso"),
          body("A p\u00e1gina de reserva inclui uma barra de progresso de 3 passos. O passo activo \u00e9 assinalado com um c\u00edrculo vermelho (#CC1F36) e texto a vermelho. Os passos inactivos t\u00eam opacidade reduzida. H\u00e1 uma linha de liga\u00e7\u00e3o subtil entre os passos."),
          gap(100),
          h3("Sidebar de sum\u00e1rio"),
          body("A sidebar permanece vis\u00edvel em cabe\u00e7alho vermelho com texto branco e corpo em cinzento claro com as linhas de detalhe da reserva. O total tem borda superior dupla e fonte maior."),
        ];
      })(),

      // ── CAP 7 ─────────────────────────────────────────────────────────────
      new Paragraph({ children: [new PageBreak()] }),
      h1("Cap\u00edtulo 7 \u2014 S\u00edntese do Web Style Guide"),

      // Cores
      h2("7.1 Paleta de Cores"),
      body("Identidade africana com vermelho como cor prim\u00e1ria, fundo escuro para nav/footer e fundos claros para conte\u00fado. Todos os pares de contraste respeitam WCAG AA."),
      gap(80),

      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [Math.floor(CW/4), Math.floor(CW/4), Math.floor(CW/4), CW - 3*Math.floor(CW/4)],
        rows: [
          headerRow(["Token", "Hex", "Amostra", "Utiliza\u00e7\u00e3o"],
            [Math.floor(CW/4), Math.floor(CW/4), Math.floor(CW/4), CW - 3*Math.floor(CW/4)]),
          new TableRow({ children: [
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Primary Red",font:"Arial",size:20})]})] }),
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"#CC1F36",font:"Arial",size:20})]})] }),
            colourCell("", "CC1F36", "CC1F36", Math.floor(CW/4)),
            new TableCell({ width:{size:CW-3*Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"CTAs, estados activos, marca",font:"Arial",size:20})]})] }),
          ]}),
          new TableRow({ children: [
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:LGRAY,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Red Hover",font:"Arial",size:20})]})] }),
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:LGRAY,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"#B01A30",font:"Arial",size:20})]})] }),
            colourCell("", "B01A30", "B01A30", Math.floor(CW/4)),
            new TableCell({ width:{size:CW-3*Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:LGRAY,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Hover de bot\u00f5es prim\u00e1rios",font:"Arial",size:20})]})] }),
          ]}),
          new TableRow({ children: [
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Dark",font:"Arial",size:20})]})] }),
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"#1C1C1E",font:"Arial",size:20})]})] }),
            colourCell("", "1C1C1E", "1C1C1E", Math.floor(CW/4)),
            new TableCell({ width:{size:CW-3*Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Navbar, rodap\u00e9, fundos dark",font:"Arial",size:20})]})] }),
          ]}),
          new TableRow({ children: [
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:LGRAY,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Gray 50",font:"Arial",size:20})]})] }),
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:LGRAY,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"#F8F9FC",font:"Arial",size:20})]})] }),
            colourCell("", "F8F9FC", "F8F9FC", Math.floor(CW/4)),
            new TableCell({ width:{size:CW-3*Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:LGRAY,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Fundos de p\u00e1gina, sec\u00e7\u00f5es alternadas",font:"Arial",size:20})]})] }),
          ]}),
          new TableRow({ children: [
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Gray 600",font:"Arial",size:20})]})] }),
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"#5A6478",font:"Arial",size:20})]})] }),
            colourCell("", "5A6478", "5A6478", Math.floor(CW/4)),
            new TableCell({ width:{size:CW-3*Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Texto secund\u00e1rio, r\u00f3tulos",font:"Arial",size:20})]})] }),
          ]}),
          new TableRow({ children: [
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:LGRAY,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Success",font:"Arial",size:20})]})] }),
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:LGRAY,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"#1D9A6C",font:"Arial",size:20})]})] }),
            colourCell("", "1D9A6C", "1D9A6C", Math.floor(CW/4)),
            new TableCell({ width:{size:CW-3*Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:LGRAY,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Estado live, confirma\u00e7\u00e3o, porta dispon\u00edvel",font:"Arial",size:20})]})] }),
          ]}),
          new TableRow({ children: [
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Error",font:"Arial",size:20})]})] }),
            new TableCell({ width:{size:Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"#C0392B",font:"Arial",size:20})]})] }),
            colourCell("", "C0392B", "C0392B", Math.floor(CW/4)),
            new TableCell({ width:{size:CW-3*Math.floor(CW/4),type:WidthType.DXA}, borders:allBorders(), margins:{top:80,bottom:80,left:120,right:120}, shading:{fill:WHITE,type:ShadingType.CLEAR}, children:[new Paragraph({children:[new TextRun({text:"Erros de formul\u00e1rio, mensagens de erro",font:"Arial",size:20})]})] }),
          ]}),
        ]
      }),

      // Tipografia
      gap(200),
      h2("7.2 Tipografia"),
      gap(80),

      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [2000, 2800, 1800, 2426],
        rows: [
          headerRow(["Fun\u00e7\u00e3o", "Fonte", "Peso(s)", "Tamanho"], [2000, 2800, 1800, 2426]),
          dataRow(["T\u00edtulos (H1\u2013H3)", "Montserrat", "600, 700, 800", "clamp(1.5rem, 3\u20135vw, 3.5rem)"], [2000, 2800, 1800, 2426], WHITE),
          dataRow(["Corpo / texto", "Open Sans", "400, 500, 600", "0.9rem (base)"], [2000, 2800, 1800, 2426], LGRAY),
          dataRow(["R\u00f3tulos / legendas", "Open Sans", "300, 400", "0.65\u20130.78rem"], [2000, 2800, 1800, 2426], WHITE),
          dataRow(["Badges / etiquetas", "Montserrat", "600", "0.72rem (uppercase)"], [2000, 2800, 1800, 2426], LGRAY),
        ]
      }),

      // Componentes
      gap(200),
      h2("7.3 Componentes Principais"),

      h3("Navbar"),
      bullet("Altura fixa: 72 px"),
      bullet("Transparente sobre o hero, branca com borda nas restantes p\u00e1ginas"),
      bullet("5 liga\u00e7\u00f5es principais (Home, Rotas, Frota, Live, Sobre)"),
      bullet("2 bot\u00f5es de ac\u00e7\u00e3o: Login (contorno vermelho) + Reservar (vermelho preenchido)"),
      bullet("Hover: fundo vermelho claro (#FFF5F6) + texto vermelho"),
      gap(100),

      h3("Bot\u00f5es"),
      gap(60),
      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [2000, 2200, 2200, 2626],
        rows: [
          headerRow(["Variante", "Fundo", "Texto", "Hover"], [2000, 2200, 2200, 2626]),
          dataRow(["Prim\u00e1rio", "#CC1F36", "Branco", "#B01A30 + sobe 2 px"], [2000, 2200, 2200, 2626], WHITE),
          dataRow(["Secund\u00e1rio", "Transparente", "Branco", "Overlay branco suave"], [2000, 2200, 2200, 2626], LGRAY),
          dataRow(["Contorno Vermelho", "Transparente", "#CC1F36", "#FFF5F6"], [2000, 2200, 2200, 2626], WHITE),
          dataRow(["Dark", "#1C1C1E", "Branco", "#2D2D30 + sobe 2 px"], [2000, 2200, 2200, 2626], LGRAY),
        ]
      }),
      gap(80),
      body("Tamanhos: pequeno (8\u00d716 px, 0.72rem) | padr\u00e3o (14\u00d728 px, 0.82rem) | grande (16\u00d736 px, 0.9rem)"),
      body("Border radius: 6 px (sm) | 12 px (md) | 20 px (lg) | 32 px (xl)"),

      gap(120),
      h3("Widget de Pesquisa"),
      bullet("Card glassmorphic, sombra grande, borda arredondada (radius-xl)"),
      bullet("Tabs: Ida e volta / S\u00f3 ida / V\u00e1rias cidades (fundo cinzento, activo a vermelho)"),
      bullet("Grelha de 4 colunas no desktop: Origem | Destino | Data | Classe"),
      bullet("Bot\u00e3o de pesquisa vermelho, uppercase, largura total da linha"),
      bullet("Campos: borda 1.5 px cinzento, foco com borda vermelha + sombra vermelha suave"),

      gap(120),
      h3("Card de Voo (Resultados)"),
      bullet("Fundo branco, borda 1.5 px, arredondado"),
      bullet("Cabe\u00e7alho: hora de partida | seta vermelha + dura\u00e7\u00e3o | hora de chegada"),
      bullet("C\u00f3digo ICAO do aeroporto em cinzento claro, uppercase"),
      bullet("Grelha de pre\u00e7os: 3 colunas (Econ\u00f3mica / Business / Primeira) com bot\u00e3o de selec\u00e7\u00e3o"),

      gap(120),
      h3("Mapa de Assentos"),
      bullet("Grelha de 7 colunas, assentos 32\u00d732 px"),
      bullet("Livre: fundo branco, borda cinzenta"),
      bullet("Seleccionado: fundo #CC1F36, texto branco"),
      bullet("Ocupado: fundo #F0F2F7, cursor desactivado"),
      bullet("Zonas: Primeira Classe (tint vermelho), Business (tint azul), Econ\u00f3mica (neutro)"),

      gap(120),
      h3("Cards de Aeronave (Frota)"),
      bullet("Largura fixa 300 px, imagem 200 px, corpo com padding 22 px"),
      bullet("Badge de categoria (canto sup. esq.): Regional=azul, Curto raio=verde, Longo raio=vermelho"),
      bullet("Badge de hub (canto sup. dir.): fundo escuro"),
      bullet("Hover: sobe 8 px, sombra grande, borda com tint vermelho"),

      gap(120),
      h3("Card de Confirma\u00e7\u00e3o"),
      bullet("Centrado, fundo branco, border-radius xl"),
      bullet("\u00cdcone de check em c\u00edrculo verde"),
      bullet("C\u00f3digo de reserva em monospace, borda tracejada"),

      gap(120),
      h3("Rodap\u00e9"),
      bullet("Fundo escuro (#1C1C1E)"),
      bullet("Grelha de 4 colunas: Logo + descri\u00e7\u00e3o | Destinos | Empresa | Suporte"),
      bullet("T\u00edtulos das colunas: vermelho-400, uppercase, fonte pequena"),
      bullet("\u00cdcones sociais: c\u00edrculos de 36 px, hover com tint vermelho"),

      gap(120),
      h3("Painel de Administra\u00e7\u00e3o"),
      bullet("Sidebar fixa: 240 px, fundo escuro"),
      bullet("Grupos de navega\u00e7\u00e3o com \u00edcones SVG"),
      bullet("Estado activo: fundo vermelho claro + texto vermelho"),
      bullet("Widgets de estat\u00edsticas: valor grande (1.8 rem), \u00edcone colorido 44\u00d744 px"),

      // ── CAP 8 ─────────────────────────────────────────────────────────────
      new Paragraph({ children: [new PageBreak()] }),
      h1("Cap\u00edtulo 8 \u2014 Conclus\u00e3o da Fase 2"),
      body("Esta sec\u00e7\u00e3o deve ligar cada constatat\u00e7\u00e3o da pesquisa (N1\u2013N4) \u00e0s decis\u00f5es de design implementadas. Preencher com os resultados reais da investiga\u00e7\u00e3o."),
      gap(120),

      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [600, 3200, 5226],
        rows: [
          headerRow(["#", "Constatat\u00e7\u00e3o da Pesquisa", "Decis\u00e3o de Design que Responde"], [600, 3200, 5226]),
          dataRow(["N1", "[preencher]", "Ex.: Utilizadores n\u00e3o encontravam rotas \u2192 Widget de pesquisa proeminente no hero + p\u00e1gina de Rotas com mapa interactivo"], [600, 3200, 5226], WHITE),
          dataRow(["N2", "[preencher]", "Ex.: Fluxo de reserva era confuso \u2192 Barra de progresso de 3 passos + sidebar de sum\u00e1rio persistente"], [600, 3200, 5226], LGRAY),
          dataRow(["N3", "[preencher]", "Ex.: Informa\u00e7\u00e3o sobre frota era dif\u00edcil de encontrar \u2192 P\u00e1gina de Frota com filtros por categoria e modal de detalhe"], [600, 3200, 5226], WHITE),
          dataRow(["N4", "[preencher]", "Ex.: Opera\u00e7\u00f5es live eram um diferenciador \u2192 P\u00e1gina dedicada de Opera\u00e7\u00f5es VATSIM no menu principal"], [600, 3200, 5226], LGRAY),
        ]
      }),

      gap(200),
      note("Substituir os textos entre [preencher] e os exemplos acima pelos resultados reais da pesquisa de utilizadores."),

      // ── STYLE GUIDE AUTÓNOMO ─────────────────────────────────────────────
      new Paragraph({ children: [new PageBreak()] }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 720, after: 120 },
        children: [new TextRun({ text: "WEB STYLE GUIDE", font: "Arial", size: 48, bold: true, color: RED })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 80, after: 80 },
        children: [new TextRun({ text: "Africana Airways \u2014 Documento Aut\u00f3nomo", font: "Arial", size: 28, color: DGRAY, italics: true })]
      }),
      divider(),

      // Paleta completa
      h2("1. Paleta de Cores"),
      body("Identidade visual baseada em vermelho africano intenso (#CC1F36), fundos escuros para zonas de navega\u00e7\u00e3o e fundos claros para conte\u00fado. Contraste m\u00ednimo WCAG AA em todos os pares."),
      gap(80),

      h3("Cores Prim\u00e1rias"),
      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [2256, 2256, 2256, 2258],
        rows: [
          new TableRow({ children: [
            colourCell("#7A0D1E\nRed 900", "7A0D1E", "FFFFFF", 2256),
            colourCell("#9E1226\nRed 800", "9E1226", "FFFFFF", 2256),
            colourCell("#CC1F36\nRed 600 (principal)", "CC1F36", "FFFFFF", 2256),
            colourCell("#E02040\nRed 500", "E02040", "FFFFFF", 2258),
          ]}),
          new TableRow({ children: [
            colourCell("#FEF0F2\nRed 100", "FEF0F2", "CC1F36", 2256),
            colourCell("#FFF5F6\nRed 50", "FFF5F6", "CC1F36", 2256),
            colourCell("#1C1C1E\nDark", "1C1C1E", "FFFFFF", 2256),
            colourCell("#2D2D30\nDark 700", "2D2D30", "FFFFFF", 2258),
          ]}),
        ]
      }),

      gap(120),
      h3("Neutros"),
      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [2256, 2256, 2256, 2258],
        rows: [
          new TableRow({ children: [
            colourCell("#F8F9FC\nGray 50", "F8F9FC", "1C1C1E", 2256),
            colourCell("#F0F2F7\nGray 100", "F0F2F7", "1C1C1E", 2256),
            colourCell("#C8CEDC\nGray 300", "C8CEDC", "1C1C1E", 2256),
            colourCell("#9AA3B8\nGray 400", "9AA3B8", "1C1C1E", 2258),
          ]}),
          new TableRow({ children: [
            colourCell("#5A6478\nGray 600", "5A6478", "FFFFFF", 2256),
            colourCell("#2D3346\nGray 800", "2D3346", "FFFFFF", 2256),
            colourCell("#1D9A6C\nSuccess", "1D9A6C", "FFFFFF", 2256),
            colourCell("#C0392B\nError", "C0392B", "FFFFFF", 2258),
          ]}),
        ]
      }),

      // Tipografia completa
      gap(200),
      h2("2. Tipografia"),
      gap(80),
      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [1800, 2400, 1600, 1600, 1626],
        rows: [
          headerRow(["N\u00edvel", "Fonte", "Peso", "Tamanho", "Uso"], [1800, 2400, 1600, 1600, 1626]),
          dataRow(["H1", "Montserrat", "800", "clamp(2rem,5vw,3.5rem)", "T\u00edtulos hero"], [1800, 2400, 1600, 1600, 1626], WHITE),
          dataRow(["H2", "Montserrat", "700", "clamp(1.5rem,3vw,2.4rem)", "T\u00edtulos de sec\u00e7\u00e3o"], [1800, 2400, 1600, 1600, 1626], LGRAY),
          dataRow(["H3", "Montserrat", "600", "clamp(1.1rem,2vw,1.5rem)", "Sub-t\u00edtulos"], [1800, 2400, 1600, 1600, 1626], WHITE),
          dataRow(["Body", "Open Sans", "400", "0.9rem", "Texto de conte\u00fado"], [1800, 2400, 1600, 1600, 1626], LGRAY),
          dataRow(["Small", "Open Sans", "400", "0.78\u20130.85rem", "Descri\u00e7\u00f5es, hints"], [1800, 2400, 1600, 1600, 1626], WHITE),
          dataRow(["Label", "Open Sans", "300", "0.65\u20130.72rem", "R\u00f3tulos uppercase"], [1800, 2400, 1600, 1600, 1626], LGRAY),
        ]
      }),

      // Componentes UI
      gap(200),
      h2("3. Componentes UI"),

      h3("3.1 Bot\u00f5es"),
      gap(60),
      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [2000, 2000, 1800, 1800, 1426],
        rows: [
          headerRow(["Nome", "Fundo", "Texto", "Borda", "Hover"], [2000, 2000, 1800, 1800, 1426]),
          dataRow([".btn-primary", "#CC1F36", "Branco", "Nenhuma", "#B01A30 + sobe"], [2000, 2000, 1800, 1800, 1426], WHITE),
          dataRow([".btn-secondary", "Transparente", "Branco", "1.5px branca", "Overlay branco"], [2000, 2000, 1800, 1800, 1426], LGRAY),
          dataRow([".btn-outline-red", "Transparente", "#CC1F36", "1.5px #CC1F36", "#FFF5F6"], [2000, 2000, 1800, 1800, 1426], WHITE),
          dataRow([".btn-dark", "#1C1C1E", "Branco", "Nenhuma", "#2D2D30"], [2000, 2000, 1800, 1800, 1426], LGRAY),
        ]
      }),
      gap(80),
      body("Padding: sm 8\u00d716 px | padr\u00e3o 14\u00d728 px | lg 16\u00d736 px"),
      body("Font-size: sm 0.72rem | padr\u00e3o 0.82rem | lg 0.9rem"),
      body("Transi\u00e7\u00e3o: all 0.25s cubic-bezier(0.4, 0, 0.2, 1)"),
      body("Estados: normal | hover (sobe 2px + sombra) | disabled (opacidade 0.5, cursor: not-allowed)"),

      gap(160),
      h3("3.2 Campos de Formul\u00e1rio"),
      bullet("Fundo: #F0F2F7 (inactivo) | Branco (activo)"),
      bullet("Borda: 1.5px #C8CEDC normal | 1.5px #CC1F36 no foco"),
      bullet("Sombra no foco: 0 0 0 3px rgba(204,31,54,0.12)"),
      bullet("Border radius: 8\u201312 px"),
      bullet("Padding: 12\u201316 px"),
      bullet("Placeholder: #9AA3B8"),
      bullet("Erro: borda #C0392B + mensagem de erro abaixo em vermelho 0.78rem"),

      gap(160),
      h3("3.3 Menus / Navbar"),
      bullet("Altura: 72 px, position: fixed, top: 0"),
      bullet("z-index elevado para sobrepor conte\u00fado"),
      bullet("Modo hero: background transparent"),
      bullet("Modo normal: background #FFFFFF, border-bottom 1px #E2E6EF"),
      bullet("Links: hover com fundo #FFF5F6 e texto #CC1F36"),
      bullet("Bot\u00f5es de ac\u00e7\u00e3o no lado direito: Login + Reservar"),
      bullet("Mobile (<768 px): menu hamburger collaps\u00e1vel"),

      gap(160),
      h3("3.4 \u00cdcones"),
      bullet("SVGs inline ao longo de toda a interface"),
      bullet("Tamanho padr\u00e3o: 16\u201324 px"),
      bullet("Cor: herda do texto ou cor espec\u00edfica de contexto"),
      bullet("Caixas de \u00edcone: 44\u201352 px com fundo colorido (admin/features)"),

      gap(160),
      h3("3.5 Cards de Voo"),
      bullet("Fundo: #FFFFFF | Borda: 1.5px #E2E6EF | Border-radius: 12 px"),
      bullet("Cabe\u00e7alho: hora partida | seta + dura\u00e7\u00e3o | hora chegada"),
      bullet("C\u00f3digos ICAO em uppercase, 0.78rem, #9AA3B8"),
      bullet("Grelha de pre\u00e7os: 3 colunas iguais"),
      bullet("Borda inferior da row activa: 2px #CC1F36"),
      bullet("Hover: sombra md + borda com tint vermelho"),

      gap(160),
      h3("3.6 Mapa de Assentos"),
      bullet("Grelha de 7 colunas, gap 4 px"),
      bullet("Assento: 32\u00d732 px, border-radius 4 px, font-size 0.65rem"),
      bullet("Livre: #FFFFFF, borda #C8CEDC"),
      bullet("Seleccionado: #CC1F36, texto branco"),
      bullet("Ocupado: #F0F2F7, cursor: not-allowed"),
      bullet("Corredor: sem fundo nem borda (espa\u00e7o visual)"),
      bullet("Primeira Classe: tint #FEF0F2 | Business: tint azul | Econ\u00f3mica: neutro"),

      gap(200),
      h2("4. Espa\u00e7amento e Sombras"),
      gap(60),
      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [2000, 3000, 4026],
        rows: [
          headerRow(["Token", "Valor", "Uso"], [2000, 3000, 4026]),
          dataRow(["--radius-sm", "6 px", "Bot\u00f5es pequenos, badges"], [2000, 3000, 4026], WHITE),
          dataRow(["--radius-md", "12 px", "Cards, inputs, modais"], [2000, 3000, 4026], LGRAY),
          dataRow(["--radius-lg", "20 px", "Sec\u00e7\u00f5es, hero widgets"], [2000, 3000, 4026], WHITE),
          dataRow(["--radius-xl", "32 px", "Cards de confirma\u00e7\u00e3o, CTAs grandes"], [2000, 3000, 4026], LGRAY),
          dataRow(["--shadow-sm", "0 2px 8px rgba(0,0,0,0.07)", "Cards em repouso"], [2000, 3000, 4026], WHITE),
          dataRow(["--shadow-md", "0 4px 20px rgba(0,0,0,0.10)", "Cards em hover"], [2000, 3000, 4026], LGRAY),
          dataRow(["--shadow-lg", "0 8px 40px rgba(0,0,0,0.14)", "Modais, popovers"], [2000, 3000, 4026], WHITE),
          dataRow(["--shadow-xl", "0 16px 64px rgba(0,0,0,0.18)", "Hero widgets, CTAs"], [2000, 3000, 4026], LGRAY),
        ]
      }),

      gap(200),
      h2("5. Responsividade"),
      gap(80),
      new Table({
        width: { size: CW, type: WidthType.DXA },
        columnWidths: [2000, 3000, 4026],
        rows: [
          headerRow(["Breakpoint", "Largura", "Comportamento"], [2000, 3000, 4026]),
          dataRow(["Desktop", "\u2265 1024 px", "Layout completo multi-coluna, sidebar vis\u00edvel"], [2000, 3000, 4026], WHITE),
          dataRow(["Tablet", "768\u20131024 px", "Grelhas passam para 2 colunas, ajustes de font-size"], [2000, 3000, 4026], LGRAY),
          dataRow(["Mobile", "< 768 px", "1 coluna, navbar hamburger, bot\u00f5es full-width"], [2000, 3000, 4026], WHITE),
          dataRow(["Tipografia", "Qualquer", "clamp() em todos os t\u00edtulos (fluida entre breakpoints)"], [2000, 3000, 4026], LGRAY),
        ]
      }),

      // Nota final
      gap(200),
      divider(),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 120, after: 60 },
        children: [new TextRun({ text: "Africana Virtual Airways \u2014 UI/UX Briefing \u2014 Abril 2026", font: "Arial", size: 20, color: DGRAY, italics: true })]
      }),

    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("D:/My Projects/afv-tracker/AFV_UIX_Briefing.docx", buffer);
  console.log("Documento gerado: AFV_UIX_Briefing.docx");
});
