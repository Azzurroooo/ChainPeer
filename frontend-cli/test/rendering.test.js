import assert from "node:assert/strict";
import test from "node:test";

import { AssistantRenderer } from "../lib/assistant-renderer.js";
import { startupText, toolRequestedLine, toolResultLine } from "../lib/rendering.js";

test("startupText includes resume preview when provided", () => {
  assert.equal(
    startupText({
      model: "m1",
      session_id: "s1",
      resume_preview: "Resumed session s1",
    }),
    "ChainPeer m1 session s1\n\nResumed session s1",
  );
});

test("toolRequestedLine shows bash command", () => {
  assert.equal(
    toolRequestedLine({
      tool_name: "bash",
      args_preview: '{"command":"date"}',
    }),
    "Running bash: date",
  );
});

test("toolResultLine matches Python CLI wording", () => {
  assert.equal(
    toolResultLine({
      tool_name: "bash",
      status: "completed",
      duration_ms: 1250,
    }),
    "Tool: bash completed in 1.25s",
  );
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
