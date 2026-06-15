import assert from "node:assert/strict";
import test from "node:test";

import { AssistantRenderer } from "../lib/assistant-renderer.js";
import {
  answerHintText,
  answerPromptText,
  answerPlaceholderText,
  cancelledText,
  commandResultText,
  contextBuiltLine,
  errorLine,
  helpText,
  interruptText,
  modelUsageText,
  optionLine,
  promptText,
  promptPlaceholderText,
  questionHeader,
  skillLine,
  startupText,
  tokenStatsLine,
  toolProgressLine,
  toolRequestedLine,
  toolResultLine,
  toolStartedLine,
  turnCompletedLine,
  turnStartText,
  unknownCommandText,
} from "../lib/rendering.js";

test("startupText includes resume preview when provided", () => {
  assert.equal(
    startupText({
      model: "m1",
      session_id: "s1",
      resume_preview: "Resumed session s1\nuser: hello\nassistant: hi",
    }),
    `ChainPeer agent runtime\n  m1 · session s1\n  ${process.cwd()}\n\n  Resumed session s1\n  ↳ user · hello\n  ↳ assistant · hi`,
  );
});

test("startupText clips long resume preview lines", () => {
  const text = startupText({
    resume_preview: `user: ${"x".repeat(120)}`,
  });

  assert.match(text, /\u21b3 user · x{69}\.\.\./);
});

test("startupText clips long cwd in the middle", () => {
  const cwd = `E:\\${"deep\\".repeat(20)}project`;
  const text = startupText({
    model: "m1",
    session_id: "s1",
    cwd,
  });
  const cwdLine = text.split("\n")[2].trim();

  assert.ok(cwdLine.length <= 76);
  assert.ok(cwdLine.startsWith("E:\\deep"));
  assert.ok(cwdLine.endsWith("\\project"));
  assert.ok(cwdLine.includes("..."));
  assert.notEqual(cwdLine, cwd);
});

test("prompt and turn status copy match the compact terminal UI", () => {
  assert.equal(
    promptText(),
    "\n╭─ input\n  ? shortcuts · ↑ history · /compact · /model set <model> · ctrl+c to exit\n╰─ › ",
  );
  assert.equal(promptPlaceholderText(), "Ask ChainPeer to do anything");
  assert.equal(answerPromptText(), "\n╭─ answer\n╰─ › ");
  assert.equal(answerPlaceholderText(), "Answer");
  assert.equal(turnStartText(), "• Working (ctrl+c to interrupt)\n");
  assert.equal(interruptText(), "• Interrupt requested (ctrl+c again to quit)");
  assert.equal(cancelledText(), "• Interrupted session state preserved; resume with -c");
});

test("promptText includes compact session status when available", () => {
  assert.equal(
    promptText({ model: "glm-5.1", cwd: "E:\\code\\agent\\agent_base-ts-cli-process-split" }, {
      context_usage_percent: 0.125,
    }),
    "\n╭─ input\n  glm-5.1 · 88% context left · E:\\code\\agent\\agent_base-ts-cli-process-split\n  ? shortcuts · ↑ history · /compact · /model set <model> · ctrl+c to exit\n╰─ › ",
  );
});

test("helpText renders compact shortcuts and commands", () => {
  assert.equal(
    helpText(),
    [
      "  Shortcuts: ↑/↓ history · ctrl+c interrupt or exit",
      "  Commands: /compact · /model set <model> · /clear · /exit",
    ].join("\n"),
  );
});

test("unknownCommandText points to shortcuts help", () => {
  assert.equal(unknownCommandText(), "• Unknown command type ? for shortcuts");
});

test("modelUsageText renders concrete model command usage", () => {
  assert.equal(modelUsageText(), "  Usage: /model set <model>");
});

test("commandResultText renders a compact success line", () => {
  assert.equal(commandResultText("Model updated: glm-5.1"), "✓ Model updated: glm-5.1");
});

test("contextBuiltLine warns only when ChainPeer docs are truncated", () => {
  assert.equal(contextBuiltLine({ decisions: {} }), "");
  assert.equal(
    contextBuiltLine({
      decisions: {
        chainpeer_docs_truncated: true,
        chainpeer_docs_truncated_scopes: ["user", "project"],
      },
    }),
    "• CHAINPEER.md truncated for context: user, project",
  );
});

test("toolRequestedLine shows bash command", () => {
  assert.equal(
    toolRequestedLine({
      tool_name: "bash",
      args_preview: '{"command":"date"}',
    }),
    "• Running bash\n  └ date",
  );
});

test("toolRequestedLine clips long details", () => {
  const line = toolRequestedLine({
    tool_name: "bash",
    args_preview: JSON.stringify({ command: `echo ${"x".repeat(140)}` }),
  });

  assert.equal(line.split("\n")[1].length, "  └ ".length + 96);
  assert.match(line, /\.\.\.$/);
});

test("toolStartedLine renders fallback running state", () => {
  assert.equal(toolStartedLine({ tool_name: "bash" }), "• Running bash");
});

test("toolResultLine renders compact success state", () => {
  assert.equal(
    toolResultLine({
      tool_name: "bash",
      status: "completed",
      duration_ms: 1250,
    }),
    "✓ bash completed in 1.25s",
  );
});

test("toolResultLine includes compact failure detail", () => {
  assert.equal(
    toolResultLine({
      tool_name: "bash",
      status: "failed",
      error_type: "Timeout",
      duration_ms: 50,
      result: '{"ok":false,"error":"command timed out\\ntry again"}',
    }),
    "× bash failed in 50ms (Timeout): command timed out try again",
  );
});

test("toolProgressLine renders compact progress messages", () => {
  assert.equal(
    toolProgressLine({
      tool_name: "bash",
      payload: { message: "waiting\nfor output" },
    }),
    "• bash\n  └ waiting for output",
  );
  assert.equal(toolProgressLine({ tool_name: "bash", payload: { stdout: "ignored" } }), "");
});

test("tokenStatsLine renders compact context status", () => {
  assert.equal(
    tokenStatsLine({
      stats: {
        input_tokens: 121300,
        effective_context_window_tokens: 245480,
        context_usage_percent: 121300 / 245480,
        cache_hit_rate: 98700 / 121300,
        output_tokens: 2100,
      },
    }),
    "• Context 49% used · cache 81.4% · output 2.1k",
  );
});

test("turnCompletedLine renders duration and tool summary", () => {
  assert.equal(
    turnCompletedLine({ duration_ms: 2000 }, { completed: 2, failed: 1 }),
    "✓ Done in 2.00s · 2 tools, 1 failed",
  );
  assert.equal(turnCompletedLine({ duration_ms: 0 }), "✓ Done in 0ms");
});

test("status helpers render question, skill, and errors", () => {
  assert.equal(questionHeader("Pick one"), "? Pick one");
  assert.equal(optionLine("A", 0, "A"), "› 1. A recommended");
  assert.equal(optionLine("B", 1, "A"), "  2. B");
  assert.equal(answerHintText(["A", "B"]), "  Type a number or enter a custom answer");
  assert.equal(answerHintText([]), "");
  assert.equal(skillLine({ skill_name: "debugging" }), "• Using skill debugging");
  assert.equal(errorLine("failed"), "× failed");
});

test("AssistantRenderer removes markdown markers at message boundary", () => {
  let output = "";
  const renderer = new AssistantRenderer((text) => {
    output += text;
  }, { color: false });

  renderer.append("现在是 **2026年6月11日**，路径是 `frontend-cli`。");
  renderer.finish();

  assert.equal(output, "现在是 2026年6月11日，路径是 frontend-cli。\n");
});

test("AssistantRenderer renders headings and lists without raw markdown prefixes", () => {
  let output = "";
  const renderer = new AssistantRenderer((text) => {
    output += text;
  }, { color: false });

  renderer.append("## 标题\n- **重点** 项\n");
  renderer.finish();

  assert.equal(output, "标题\n• 重点 项\n");
});

test("AssistantRenderer renders code fences as compact labels", () => {
  let output = "";
  const renderer = new AssistantRenderer((text) => {
    output += text;
  }, { color: false });

  renderer.append("```sh\necho hi\n```\n");
  renderer.finish();

  assert.equal(output, "  ┌ code sh\necho hi\n  └ end\n");
});

test("AssistantRenderer applies ansi styles when color is enabled", () => {
  let output = "";
  const renderer = new AssistantRenderer((text) => {
    output += text;
  }, { color: true });

  renderer.append("**重点** 和 `code`");
  renderer.finish();

  assert.match(output, /\x1b\[1m重点\x1b\[0m/);
  assert.match(output, /\x1b\[1;36mcode\x1b\[0m/);
});
