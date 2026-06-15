export function startupText(info) {
  const header = [
    `${bold("ChainPeer")} ${dim("agent runtime")}`,
    dim(`  ${info.model || "unknown"} · session ${info.session_id || "unknown"}`),
    dim(`  ${middleClip(info.cwd || process.cwd(), 76)}`),
  ].join("\n");
  const preview = resumePreviewText(info.resume_preview);
  return preview ? `${header}\n\n${preview}` : header;
}

export function promptText(info = {}, stats = {}) {
  return inputPromptFrame("input", [promptStatusLine(info, stats), inputFooter()]);
}

export function promptPlaceholderText() {
  return dim("Ask ChainPeer to do anything");
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
  return inputPromptFrame("answer");
}

export function answerPlaceholderText() {
  return dim("Answer");
}

export function turnStartText() {
  return `${cyan("•")} Working ${dim("(ctrl+c to interrupt)")}\n`;
}

export function turnCompletedLine(event, tools = { completed: 0, failed: 0 }) {
  const duration = formatDuration(event.duration_ms);
  const summary = toolSummary(tools);
  return summary ? `${green("✓")} Done in ${duration} · ${summary}` : `${green("✓")} Done in ${duration}`;
}

export function interruptText() {
  return `${yellow("•")} Interrupt requested ${dim("(ctrl+c again to quit)")}`;
}

export function cancelledText() {
  return `${yellow("•")} Interrupted ${dim("session state preserved; resume with -c")}`;
}

export function commandResultText(text) {
  return `${green("✓")} ${text}`;
}

export function modelUsageText() {
  return `${dim("  Usage: /model set <model>")}`;
}

export function contextBuiltLine(event) {
  const decisions = event.decisions && typeof event.decisions === "object" ? event.decisions : {};
  if (!decisions.chainpeer_docs_truncated) {
    return "";
  }
  const scopes = Array.isArray(decisions.chainpeer_docs_truncated_scopes)
    ? decisions.chainpeer_docs_truncated_scopes.join(", ")
    : "unknown";
  return `${yellow("•")} CHAINPEER.md truncated for context: ${scopes}`;
}

export function unknownCommandText() {
  return `${yellow("•")} Unknown command ${dim("type ? for shortcuts")}`;
}

export function toolRequestedLine(event) {
  const name = event.tool_name || "unknown";
  const detail = toolDetail(name, parseJsonObject(event.args_preview));
  return detail ? `${cyan("•")} Running ${name}\n${dim(`  └ ${detail}`)}` : `${cyan("•")} Running ${name}`;
}

export function toolStartedLine(event) {
  return `${cyan("•")} Running ${event.tool_name || "tool"}`;
}

export function toolResultLine(event) {
  const name = event.tool_name || "unknown";
  const duration = formatDuration(event.duration_ms);
  if (event.status === "failed") {
    const suffix = event.error_type ? ` (${event.error_type})` : "";
    const detail = toolErrorDetail(event.result);
    return `${red("×")} ${name} failed in ${duration}${suffix}${detail ? `: ${detail}` : ""}`;
  }
  return `${green("✓")} ${name} completed in ${duration}`;
}

export function toolProgressLine(event) {
  const name = event.tool_name || "tool";
  const message = progressMessage(event.payload);
  return message ? `${cyan("•")} ${name}\n${dim(`  └ ${message}`)}` : "";
}

export function tokenStatsLine(event) {
  const stats = event.stats && typeof event.stats === "object" ? event.stats : {};
  const input = formatCount(stats.input_tokens);
  const window = formatCount(stats.effective_context_window_tokens);
  const context = formatPercent(stats.context_usage_percent);
  const cache = formatPercent(stats.cache_hit_rate);
  const output = formatCount(stats.output_tokens);
  return `${cyan("•")} Context ${input}/${window} (${context}) · cache ${cache} · output ${output}`;
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
  const marker = option === recommended ? bold("›") : " ";
  const suffix = option === recommended ? dim(" recommended") : "";
  return `${marker} ${index + 1}. ${option}${suffix}`;
}

export function answerHintText(options) {
  return Array.isArray(options) && options.length ? dim("  Type a number or enter a custom answer") : "";
}

function toolDetail(name, args) {
  if (name === "bash") {
    return clipSingleLine(args.command, 96);
  }
  if (name === "bash_output") {
    const bgId = clipSingleLine(args.bg_id, 96);
    return bgId ? `bg ${bgId}` : "";
  }
  for (const key of ["file_path", "path", "query", "url", "command"]) {
    const value = clipSingleLine(args[key], 96);
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

function toolErrorDetail(result) {
  const payload = parseJsonObject(result);
  return clipSingleLine(payload.error, 120);
}

function progressMessage(payload) {
  if (!payload || typeof payload !== "object") {
    return "";
  }
  for (const key of ["message", "status", "text"]) {
    const value = clipSingleLine(payload[key], 120);
    if (value) {
      return value;
    }
  }
  return "";
}

function clipSingleLine(value, maxLength) {
  const text = singleLine(value);
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxLength - 3))}...`;
}

function middleClip(value, maxLength) {
  const text = singleLine(value);
  if (text.length <= maxLength) {
    return text;
  }
  const keep = Math.max(0, maxLength - 3);
  const head = Math.ceil(keep / 2);
  const tail = Math.floor(keep / 2);
  return `${text.slice(0, head)}...${text.slice(text.length - tail)}`;
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

function toolSummary(tools) {
  const completed = Number(tools.completed || 0);
  const failed = Number(tools.failed || 0);
  const parts = [];
  if (completed > 0) {
    parts.push(`${completed} tool${completed === 1 ? "" : "s"}`);
  }
  if (failed > 0) {
    parts.push(`${failed} failed`);
  }
  return parts.join(", ");
}

function formatCount(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) {
    return "0";
  }
  if (Math.abs(number) >= 1000) {
    return `${(number / 1000).toFixed(1)}k`;
  }
  return String(Math.trunc(number));
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "0.0%";
  }
  return `${(number * 100).toFixed(1)}%`;
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

function inputPromptFrame(title, body = []) {
  const lines = [`\n${dim(`╭─ ${title}`)}`];
  for (const line of body) {
    if (line) {
      lines.push(line);
    }
  }
  lines.push(`${dim("╰─")} ${bold("›")} `);
  return lines.join("\n");
}

function promptStatusLine(info, stats) {
  const parts = [singleLine(info.model), contextLeft(stats), middleClip(info.cwd, 56)].filter(Boolean);
  return parts.length ? dim(`  ${parts.join(" · ")}`) : "";
}

function contextLeft(stats) {
  const usage = Number(stats?.context_usage_percent);
  if (!Number.isFinite(usage)) {
    return "";
  }
  const left = Math.max(0, Math.min(1, 1 - usage));
  return `${(left * 100).toFixed(0)}% context left`;
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

function yellow(text) {
  return styled(text, "33");
}

function red(text) {
  return styled(text, "31");
}
