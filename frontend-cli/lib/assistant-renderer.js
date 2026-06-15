const INLINE_TOKEN_RE = /(\[[^\]]+\]\([^)]+\)|`[^`]+`|\*\*[^*]+\*\*)/g;
const PLAIN_TEXT_RE = /[`*#>|\[]/;

export class AssistantRenderer {
  constructor(write, options = {}) {
    this.write = write;
    this.color = options.color ?? (Boolean(process.stdout.isTTY) && !process.env.NO_COLOR);
    this.pending = "";
    this.inCodeBlock = false;
    this.lineOpen = false;
  }

  append(text) {
    this.pending += String(text || "");
    while (true) {
      const newlineIndex = this.pending.indexOf("\n");
      if (newlineIndex === -1) {
        break;
      }
      const line = this.pending.slice(0, newlineIndex);
      this.pending = this.pending.slice(newlineIndex + 1);
      this.renderLine(line, true);
    }
    this.flushPlainPending();
  }

  finish() {
    if (this.pending) {
      this.renderLine(this.pending, false);
      this.pending = "";
    }
    if (this.lineOpen) {
      this.write("\n");
      this.lineOpen = false;
    }
  }

  flushPlainPending() {
    if (!this.pending || this.inCodeBlock || !isPlainLine(this.pending)) {
      return;
    }
    this.writePlain(this.pending, false);
    this.pending = "";
  }

  renderLine(line, newline) {
    if (isTableLine(line, this.inCodeBlock)) {
      this.renderTableLine(line, newline);
      return;
    }
    if (line.trim().startsWith("```")) {
      this.renderCodeFence(line, newline);
      return;
    }
    if (this.inCodeBlock || isPlainLine(line)) {
      this.writePlain(line, newline);
      return;
    }
    this.writeStyled(renderMarkdownishLine(line, this.color), newline);
  }

  renderTableLine(line, newline) {
    const cells = parseTableRow(line);
    if (!cells.length || cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))) {
      return;
    }
    const rendered = cells.map((cell, index) =>
      renderInline(cell, this.color, index === 0 ? "boldCyan" : "")
    );
    this.writeStyled(rendered.join(dim(" | ", this.color)), newline);
  }

  renderCodeFence(line, newline) {
    const opening = !this.inCodeBlock;
    this.inCodeBlock = opening;
    const label = opening ? line.trim().slice(3).trim().slice(0, 32) : "";
    this.writeStyled(dim(opening ? codeOpenLabel(label) : "  └ end", this.color), newline);
  }

  writePlain(text, newline) {
    this.write(text + (newline ? "\n" : ""));
    this.lineOpen = Boolean(text) && !newline;
  }

  writeStyled(text, newline) {
    this.write(text + (newline ? "\n" : ""));
    this.lineOpen = Boolean(text) && !newline;
  }
}

function renderMarkdownishLine(line, color) {
  const heading = line.match(/^(#{1,6})\s+(.+?)\s*$/);
  if (heading) {
    return renderInline(heading[2], color, "bold");
  }

  const quote = line.match(/^(\s*)>\s?(.*)$/);
  if (quote) {
    return `${quote[1]}${green("│ ", color)}${renderInline(quote[2], color, "green")}`;
  }

  const list = line.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
  if (list) {
    const marker = /^\d+\.$/.test(list[2]) ? list[2] : "•";
    return `${list[1]}${yellow(`${marker} `, color)}${renderInline(list[3], color)}`;
  }

  return renderInline(line, color);
}

function renderInline(text, color, baseStyle = "") {
  return String(text || "").replace(INLINE_TOKEN_RE, (token) => {
    const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      return `${renderInline(link[1], color, baseStyle)} ${dim(`(${link[2]})`, color)}`;
    }
    if (token.startsWith("`") && token.endsWith("`")) {
      return boldCyan(token.slice(1, -1), color);
    }
    if (token.startsWith("**") && token.endsWith("**")) {
      return styled(token.slice(2, -2), color, baseStyle ? `${baseStyle}Bold` : "bold");
    }
    return token;
  });
}

function isPlainLine(line) {
  if (!line) {
    return true;
  }
  if (PLAIN_TEXT_RE.test(line)) {
    return false;
  }
  const stripped = line.trimStart();
  return !stripped.match(/^([-*+]|\d+\.)\s+/);
}

function isTableLine(line, inCodeBlock) {
  const stripped = line.trim();
  return !inCodeBlock && stripped.includes("|") && stripped.split("|").length > 2;
}

function parseTableRow(line) {
  let stripped = line.trim();
  if (stripped.startsWith("|")) {
    stripped = stripped.slice(1);
  }
  if (stripped.endsWith("|")) {
    stripped = stripped.slice(0, -1);
  }
  return stripped.split("|").map((cell) => cell.trim());
}

function codeOpenLabel(label) {
  return label ? `  ┌ code ${label}` : "  ┌ code";
}

function styled(text, color, style) {
  if (!color || !style) {
    return text;
  }
  const codes = {
    bold: "1",
    boldCyan: "1;36",
    green: "32",
    greenBold: "1;32",
    boldBold: "1",
  };
  const code = codes[style] || codes.bold;
  return `\x1b[${code}m${text}\x1b[0m`;
}

function boldCyan(text, color) {
  return styled(text, color, "boldCyan");
}

function dim(text, color) {
  return color ? `\x1b[2m${text}\x1b[0m` : text;
}

function green(text, color) {
  return styled(text, color, "green");
}

function yellow(text, color) {
  return color ? `\x1b[1;33m${text}\x1b[0m` : text;
}
