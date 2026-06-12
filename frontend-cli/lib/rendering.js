export function startupText(info) {
  const header = `ChainPeer ${info.model || "unknown"} session ${info.session_id || "unknown"}`;
  const preview = String(info.resume_preview || "").trim();
  return preview ? `${header}\n\n${preview}` : header;
}

export function toolRequestedLine(event) {
  const name = event.tool_name || "unknown";
  const detail = toolDetail(name, parseJsonObject(event.args_preview));
  return detail ? `Running ${name}: ${detail}` : `Running ${name}`;
}

export function toolResultLine(event) {
  const name = event.tool_name || "unknown";
  const duration = formatDuration(event.duration_ms);
  if (event.status === "failed") {
    const suffix = event.error_type ? ` (${event.error_type})` : "";
    return `Tool: ${name} failed in ${duration}${suffix}`;
  }
  return `Tool: ${name} completed in ${duration}`;
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
