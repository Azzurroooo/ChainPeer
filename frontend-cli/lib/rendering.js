const MAX_STARTUP_BANNER_WIDTH = 80;
const MAX_COMPOSER_WIDTH = 78;

export function startupText(info = {}) {
  const header = startupBannerText(info);
  const preview = resumePreviewText(info.resume_preview);
  return preview ? `${header}\n\n${preview}` : header;
}

export function promptText(info = {}, stats = {}, state = {}) {
  return inputPromptFrame(promptHeaderLine(info), promptFooterLine(stats, state));
}

export function promptPlaceholderText() {
  return "Ask ChainPeer to do anything";
}

export function userInputText(text) {
  const body = singleLine(text);
  return body ? `${accent("›")} ${bold("You")}\n  ${body}` : "";
}

export function assistantHeaderText() {
  return `${accent("•")} ${bold("Assistant")}`;
}

export function outputBlockText(text, leading = false) {
  const body = String(text || "").trimEnd();
  return body ? `${leading ? "\n" : ""}${body}\n` : "";
}

export function helpText() {
  return [
    `${accent("•")} Controls`,
    helpRow("enter", "send message", "/", "open commands"),
    helpRow("↑ / ↓", "history", "← / →", "move cursor"),
    helpRow("home / end", "line edges", "del / backspace", "edit text"),
    helpRow("ctrl + c", "interrupt or quit", "?", "show shortcuts"),
    "",
    `${accent("•")} Command deck`,
    dim("  /status  /sessions  /skill  /init  /plan  /compact"),
    dim("  /model set <name>  /draft  /doctor  /config  /login"),
    dim("  /clear  /exit"),
  ].join("\n");
}

export function answerPromptText() {
  return `\n  ${accent("›")} `;
}

export function answerPlaceholderText() {
  return "Type your answer";
}

export function inputHintText(placeholder) {
  const text = singleLine(placeholder);
  return text ? `\x1b[s${dim(text)}\x1b[u` : "";
}

export function clearInputHintText() {
  return "\x1b[K";
}

export function slashMenuText(items, selectedIndex = 0) {
  const visible = Array.isArray(items) ? items.slice(0, 8) : [];
  if (!visible.length) {
    return "";
  }
  const lines = [dim("  Command deck")];
  for (const [index, item] of visible.entries()) {
    const active = index === selectedIndex;
    const marker = active ? accent("›") : dim("·");
    const name = active ? bold(`/${item.name}`) : dim(`/${item.name}`);
    const description = dim(clipSingleLine(item.description, 46));
    lines.push(`  ${marker} ${padRight(name, 14)} ${description}`);
  }
  lines.push(dim("    ↑↓ select · enter run · esc close · backspace edit"));
  return `${lines.join("\n")}\n`;
}

export function turnStartText() {
  return `${accent("•")} ${bold("Status")} ${dim("·")} Working ${dim("(ctrl + c to interrupt)")}`;
}

export function queuedInputText() {
  return `${accent("•")} ${bold("Status")} ${dim("·")} Queued follow-up\n${dim("  ↳ runs after the current turn")}`;
}

export function turnCompletedLine(event, tools = { completed: 0, failed: 0 }) {
  const duration = formatDuration(event.duration_ms);
  const summary = toolSummary(tools);
  return summary
    ? `${green("✓")} ${bold("Status")} ${dim("·")} Done in ${duration} · ${summary}`
    : `${green("✓")} ${bold("Status")} ${dim("·")} Done in ${duration}`;
}

export function interruptText() {
  return `${accent("•")} ${bold("Status")} ${dim("·")} Interrupt requested ${dim("(ctrl + c again to quit)")}`;
}

export function cancelledText() {
  return `${accent("•")} ${bold("Status")} ${dim("·")} Interrupted ${dim("session state preserved; resume with -c")}`;
}

export function commandResultText(text, detail = "") {
  const line = `${green("✓")} ${bold("Status")} ${dim("·")} ${clipSingleLine(text, 96)}`;
  const extra = clipSingleLine(detail, 96);
  return extra ? `${line}\n${dim(`  └ ${extra}`)}` : line;
}

export function modelUsageText() {
  return `${accent("•")} ${bold("Status")} ${dim("·")} Model command\n${dim("  └ /model set <name>")}`;
}

export function contextBuiltLine(event) {
  const decisions = event.decisions && typeof event.decisions === "object" ? event.decisions : {};
  if (!decisions.chainpeer_docs_truncated) {
    return "";
  }
  const scopes = Array.isArray(decisions.chainpeer_docs_truncated_scopes)
    ? decisions.chainpeer_docs_truncated_scopes.join(", ")
    : "unknown";
  return `${accent("•")} ${bold("Status")} ${dim("·")} Context trimmed\n${dim(`  └ CHAINPEER.md: ${clipSingleLine(scopes, 96)}`)}`;
}

export function unknownCommandText() {
  return `${accent("•")} ${bold("Status")} ${dim("·")} Unknown command\n${dim("  └ type ? for shortcuts")}`;
}

export function toolRequestedLine(event) {
  const name = event.tool_name || "unknown";
  const detail = toolDetail(name, parseJsonObject(event.args_preview));
  const label = toolLabel(name);
  const line = `${accent("•")} ${bold("Tool")} ${dim("·")} ${toolActiveVerb(name)} ${label}`;
  return detail ? `${line}\n${dim(`  └ ${detail}`)}` : line;
}

export function toolStartedLine(event) {
  const name = event.tool_name || "tool";
  return `${accent("•")} ${bold("Tool")} ${dim("·")} ${toolActiveVerb(name)} ${toolLabel(name)}`;
}

export function toolResultLine(event) {
  const name = event.tool_name || "unknown";
  const label = toolLabel(name);
  const duration = formatDuration(event.duration_ms);
  if (event.status === "failed") {
    const suffix = event.error_type ? ` (${event.error_type})` : "";
    const detail = toolErrorDetail(event.result);
    const line = `${red("×")} ${bold("Tool")} ${dim("·")} ${label} failed in ${duration}${suffix}`;
    return detail ? `${line}\n${dim(`  └ ${detail}`)}` : line;
  }
  return `${green("✓")} ${bold("Tool")} ${dim("·")} ${completedToolText(name, label)} in ${duration}`;
}

export function toolProgressLine(event) {
  const name = event.tool_name || "tool";
  const message = progressMessage(event.payload);
  return message ? `${accent("•")} ${bold("Tool")} ${dim("·")} ${toolLabel(name)}\n${dim(`  └ ${message}`)}` : "";
}

export function tokenStatsLine(event) {
  const stats = event.stats && typeof event.stats === "object" ? event.stats : {};
  const parts = [`Context ${contextRemaining(stats)}`];
  const cache = formatOptionalPercent(stats.cache_hit_rate);
  if (cache) {
    parts.push(`cache ${cache}`);
  }
  const output = formatOptionalCount(stats.output_tokens);
  if (output) {
    parts.push(`output ${output}`);
  }
  return `${accent("•")} ${bold("Status")} ${dim("·")} ${parts.join(" · ")}`;
}

export function skillLine(event) {
  return `${accent("•")} ${bold("Status")} ${dim("·")} Using skill ${dim(event.skill_name || "unknown")}`;
}

export function errorLine(error) {
  const detail = clipSingleLine(error, 120);
  return detail
    ? `${red("×")} ${bold("Status")} ${dim("·")} Turn failed\n${dim(`  └ ${detail}`)}`
    : `${red("×")} ${bold("Status")} ${dim("·")} Turn failed`;
}

export function questionText(event = {}) {
  const options = Array.isArray(event.options) ? event.options : [];
  const lines = [
    `${accent("•")} ${bold("Choice required")}`,
    "",
    `  ${clipSingleLine(event.question || "Input required", 76)}`,
  ];
  if (options.length) {
    lines.push("");
  }
  for (const [index, option] of options.entries()) {
    lines.push(questionOptionLine(option, index, event.recommended));
  }
  lines.push("");
  lines.push(dim(questionFooter(options)));
  return lines.join("\n");
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

function toolLabel(name) {
  if (name === "bash") {
    return "command";
  }
  if (name === "bash_output") {
    return "output";
  }
  const labels = {
    apply_patch: "patch",
    edit_file: "file edit",
    read_file: "file read",
    search_files: "file search",
    view_image: "image",
    web_search: "web search",
  };
  return labels[name] || humanToolName(name);
}

function toolActiveVerb(name) {
  return name === "bash" || name === "bash_output" ? "Running" : "Calling";
}

function completedToolText(name, label) {
  if (name === "bash") {
    return `Ran ${label}`;
  }
  if (name === "bash_output") {
    return `Read ${label}`;
  }
  return `Called ${label}`;
}

function humanToolName(name) {
  return singleLine(name).replace(/[_-]+/g, " ") || "tool";
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

function formatOptionalCount(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) {
    return "";
  }
  return formatCount(number);
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "0.0%";
  }
  return `${(number * 100).toFixed(1)}%`;
}

function formatOptionalPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) {
    return "";
  }
  return formatPercent(number);
}

function resumePreviewText(value) {
  const lines = String(value || "").trim().split(/\r?\n/).filter(Boolean);
  return lines.map(resumePreviewLine).join("\n");
}

function resumePreviewLine(line) {
  const message = line.match(/^-?\s*(user|assistant):\s*(.*)$/i);
  if (message) {
    const role = message[1].toLowerCase();
    const marker = role === "user" ? accent("›") : dim("•");
    const label = role === "user" ? "You" : "Assistant";
    return `${marker} ${label} ${dim("·")} ${clipSingleLine(message[2], 72)}`;
  }
  return dim(`  ${clipSingleLine(line, 78)}`);
}

function startupBannerText(info) {
  const width = startupBannerWidth();
  const modelLine = `model ${singleLine(info.model) || "unknown"} · session ${singleLine(info.session_id) || "unknown"}`;
  const cwd = middleClip(info.cwd || process.cwd(), width - 4);
  return [
    startupBannerBorder("┌", "┐", width),
    startupBannerLine(`${bold("ChainPeer")} ${dim("workbench online")}`, width),
    startupBannerLine(modelLine, width),
    startupBannerLine(cwd, width),
    startupBannerBorder("└", "┘", width),
  ].join("\n");
}

function startupBannerBorder(left, right, width) {
  return dim(`${left}${"─".repeat(width - 2)}${right}`);
}

function startupBannerLine(text, frameWidth) {
  const clean = String(text || "").replace(/[\r\n\t]+/g, " ").trimEnd();
  const width = frameWidth - 4;
  const content =
    visibleLength(clean) <= width
      ? clean
      : `${clean.slice(0, Math.max(0, width - 3))}...`;
  return `${dim("│")} ${padRight(content, width)} ${dim("│")}`;
}

function startupBannerWidth() {
  const columns = Number(process.stdout.columns);
  if (!Number.isFinite(columns) || columns <= 0) {
    return MAX_STARTUP_BANNER_WIDTH;
  }
  return Math.max(44, Math.min(MAX_STARTUP_BANNER_WIDTH, columns - 2));
}

function questionOptionLine(option, index, recommended) {
  const marker = option === recommended ? bold("›") : " ";
  const suffix = option === recommended ? dim(" recommended") : "";
  return `  ${marker} ${index + 1}. ${clipSingleLine(option, 70)}${suffix}`;
}

function questionFooter(options) {
  return options.length
    ? "  enter number or custom answer · ctrl + c to interrupt"
    : "  enter to submit answer · ctrl + c to interrupt";
}

function helpRow(leftKey, leftText, rightKey, rightText) {
  const left = `${padRight(leftKey, 12)} ${leftText}`;
  const right = `${padRight(rightKey, 14)} ${rightText}`;
  return dim(`  ${padRight(left, 33)} ${right}`);
}

function inputPromptFrame(header = "", footer = "") {
  const lines = ["", inputPromptTitle()];
  if (header) {
    lines.push(header);
  }
  lines.push(footer, inputDivider());
  lines.push(`  ${accent("›")} `);
  return lines.join("\n");
}

function inputPromptTitle() {
  return `  ${bold("ChainPeer")} ${dim("workbench")}`;
}

function inputDivider() {
  return dim(`  ${"─".repeat(composerWidth())}`);
}

function padRight(text, width) {
  return `${text}${" ".repeat(Math.max(0, width - visibleLength(text)))}`;
}

function visibleLength(text) {
  return String(text).replace(/\x1b\[[0-9;]*m/g, "").length;
}

function promptHeaderLine(info) {
  const parts = [singleLine(info.model), middleClip(info.cwd, 56)].filter(Boolean);
  return parts.length ? dim(`  ${clipSingleLine(parts.join(" · "), composerWidth())}`) : "";
}

function promptFooterLine(stats, state = {}) {
  const parts = state.running
    ? ["agent running", "enter queue", "ctrl+c interrupt", "? shortcuts"]
    : ["? shortcuts", "/ commands", "enter send", "ctrl+c quit"];
  const right = contextLeft(stats);
  const left = parts.join(" · ");
  if (!right) {
    return dim(`  ${clipSingleLine(left, composerWidth())}`);
  }
  return dim(`  ${footerColumns(left, right)}`);
}

function composerWidth() {
  const columns = Number(process.stdout.columns);
  if (!Number.isFinite(columns) || columns <= 0) {
    return MAX_COMPOSER_WIDTH;
  }
  return Math.max(44, Math.min(MAX_COMPOSER_WIDTH, columns - 4));
}

function contextLeft(stats) {
  const remaining = contextRemaining(stats);
  return remaining.endsWith("left") ? remaining.replace(" left", " context left") : "";
}

function footerColumns(left, right) {
  const width = composerWidth();
  const leftText = clipSingleLine(left, Math.max(0, width - visibleLength(right) - 1));
  const gap = width - visibleLength(leftText) - visibleLength(right);
  return `${leftText}${" ".repeat(Math.max(1, gap))}${right}`;
}

function contextRemaining(stats) {
  const usage = Number(stats?.context_usage_percent);
  if (Number.isFinite(usage)) {
    const left = Math.max(0, Math.min(1, 1 - usage));
    return `${(left * 100).toFixed(0)}% left`;
  }
  const input = formatCount(stats.input_tokens);
  const window = formatCount(stats.effective_context_window_tokens);
  return `${input}/${window}`;
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

function accent(text) {
  return styled(text, "38;5;208");
}

function green(text) {
  return styled(text, "32");
}

function red(text) {
  return styled(text, "31");
}
