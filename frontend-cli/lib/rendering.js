export function startupText(info) {
  const header = `${bold("ChainPeer")} ${dim(info.model || "unknown")} ${dim(`session ${info.session_id || "unknown"}`)}`;
  const preview = resumePreviewText(info.resume_preview);
  const footer = statusLine(info);
  return preview ? `${header}\n\n${preview}\n\n${footer}` : `${header}\n\n${footer}`;
}

export function promptText() {
  return `\n${bold("›")} Ask ChainPeer to do anything\n${inputFooter()}\n${bold("›")} `;
}

export function helpText() {
  return [
    dim("  Shortcuts"),
    "  ↑ / ↓      history",
    "  ctrl+c     interrupt or exit",
    "",
    dim("  Commands"),
    "  /compact   compact context",
    "  /model set <model>",
    "  /clear",
    "  /exit",
  ].join("\n");
}

export function answerPromptText() {
  return `\n${bold("›")} Answer\n${bold("›")} `;
}

export function turnStartText() {
  return `${dim("  Working... ctrl+c to interrupt, ctrl+c again to quit")}\n`;
}

export function interruptText() {
  return `${dim("  interrupt requested; ctrl+c again to quit")}`;
}

export function cancelledText() {
  return dim("  Interrupted. Session state preserved; resume with -c.");
}

export function commandResultText(text) {
  return `${dim("  ")}${text}`;
}

export function unknownCommandText() {
  return dim("  Unknown command.");
}

export function toolRequestedLine(event) {
  const name = event.tool_name || "unknown";
  const detail = toolDetail(name, parseJsonObject(event.args_preview));
  return detail ? `${cyan("•")} Running ${name}: ${dim(detail)}` : `${cyan("•")} Running ${name}`;
}

export function toolStartedLine(event) {
  return `${cyan("•")} Running ${event.tool_name || "tool"}`;
}

export function toolResultLine(event) {
  const name = event.tool_name || "unknown";
  const duration = formatDuration(event.duration_ms);
  if (event.status === "failed") {
    const suffix = event.error_type ? ` (${event.error_type})` : "";
    return `${red("×")} ${name} failed in ${duration}${suffix}`;
  }
  return `${green("✓")} ${name} completed in ${duration}`;
}

export function skillLine(event) {
  return `${cyan("•")} Using skill ${dim(event.skill_name || "unknown")}`;
}

export function errorLine(error) {
  return `${red("×")} ${error || "Turn failed"}`;
}

export function questionHeader(question) {
  return `${cyan("?")} ${question || "Input required"}`;
}

export function optionLine(option, index, recommended) {
  const suffix = option === recommended ? dim(" recommended") : "";
  return `  ${index + 1}. ${option}${suffix}`;
}

function toolDetail(name, args) {
  if (name === "bash") {
    return singleLine(args.command);
  }
  if (name === "bash_output") {
    const bgId = singleLine(args.bg_id);
    return bgId ? `bg ${bgId}` : "";
  }
  for (const key of ["file_path", "path", "query", "url", "command"]) {
    const value = singleLine(args[key]);
    if (value) {
      return value;
    }
  }
  return "";
}

function parseJsonObject(value) {
  try {
    const parsed = JSON.parse(String(value || ""));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function singleLine(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function formatDuration(durationMs) {
  const value = Number(durationMs || 0);
  if (!Number.isFinite(value) || value <= 0) {
    return "0ms";
  }
  if (value < 1000) {
    return `${Math.trunc(value)}ms`;
  }
  return `${(value / 1000).toFixed(2)}s`;
}

function statusLine(info) {
  const parts = [info.model || "unknown", process.cwd()];
  return dim(`  ${parts.join(" · ")} · ctrl+c to exit`);
}

function resumePreviewText(value) {
  const lines = String(value || "").trim().split(/\r?\n/).filter(Boolean);
  return lines.map(resumePreviewLine).join("\n");
}

function resumePreviewLine(line) {
  const message = line.match(/^(user|assistant):\s*(.*)$/i);
  if (message) {
    return `${dim("  ↳")} ${message[1].toLowerCase()} · ${message[2]}`;
  }
  return dim(`  ${line}`);
}

function inputFooter() {
  return dim("  ? shortcuts · ↑ history · /compact · /model set <model> · ctrl+c to exit");
}

function styled(text, code) {
  if (!Boolean(process.stdout.isTTY) || process.env.NO_COLOR) {
    return text;
  }
  return `\x1b[${code}m${text}\x1b[0m`;
}

function bold(text) {
  return styled(text, "1");
}

function dim(text) {
  return styled(text, "2");
}

function cyan(text) {
  return styled(text, "36");
}

function green(text) {
  return styled(text, "32");
}

function red(text) {
  return styled(text, "31");
}
