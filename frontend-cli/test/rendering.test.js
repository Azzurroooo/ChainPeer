import assert from "node:assert/strict";
import test from "node:test";

import { AssistantRenderer } from "../lib/assistant-renderer.js";
import {
  answerPromptText,
  cancelledText,
  errorLine,
  helpText,
  interruptText,
  optionLine,
  promptText,
  questionHeader,
  skillLine,
  startupText,
  toolRequestedLine,
  toolResultLine,
  toolStartedLine,
  turnStartText,
} from "../lib/rendering.js";

test("startupText includes resume preview when provided", () => {
  assert.equal(
    startupText({
      model: "m1",
      session_id: "s1",
      resume_preview: "Resumed session s1",
    }),
    `ChainPeer m1 session s1\n\nResumed session s1\n\n  m1 · ${process.cwd()} · ctrl+c to exit`,
  );
});

test("prompt and turn status copy match the compact terminal UI", () => {
  assert.equal(
    promptText(),
    "\n› Ask ChainPeer to do anything\n  ? shortcuts · ↑ history · /compact · /model set <model> · ctrl+c to exit\n› ",
  );
  assert.equal(answerPromptText(), "\n› Answer\n› ");
  assert.equal(turnStartText(), "  Working... ctrl+c to interrupt, ctrl+c again to quit\n");
  assert.equal(interruptText(), "  interrupt requested; ctrl+c again to quit");
  assert.equal(cancelledText(), "  Interrupted. Session state preserved; resume with -c.");
});

test("helpText renders compact shortcuts and commands", () => {
  assert.equal(
    helpText(),
    [
      "  Shortcuts",
      "  ↑ / ↓      history",
      "  ctrl+c     interrupt or exit",
      "",
      "  Commands",
      "  /compact   compact context",
      "  /model set <model>",
      "  /clear",
      "  /exit",
    ].join("\n"),
  );
});

test("toolRequestedLine shows bash command", () => {
  assert.equal(
    toolRequestedLine({
      tool_name: "bash",
      args_preview: '{"command":"date"}',
    }),
    "• Running bash: date",
  );
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

test("status helpers render question, skill, and errors", () => {
  assert.equal(questionHeader("Pick one"), "? Pick one");
  assert.equal(optionLine("A", 0, "A"), "  1. A recommended");
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

  assert.equal(output, "标题\n- 重点 项\n");
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
