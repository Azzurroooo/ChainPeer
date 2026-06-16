import assert from "node:assert/strict";
import test from "node:test";

import { AssistantRenderer } from "../lib/assistant-renderer.js";
import {
  answerPromptText,
  answerPlaceholderText,
  cancelledText,
  clearInputHintText,
  commandResultText,
  contextBuiltLine,
  errorLine,
  helpText,
  inputHintText,
  interruptText,
  modelUsageText,
  promptText,
  promptPlaceholderText,
  questionText,
  queuedInputText,
  skillLine,
  slashMenuText,
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
      cwd: "E:\\project",
      resume_preview: "Resumed session s1\n- user: hello\n- assistant: hi",
    }),
    [
      `┌${"─".repeat(78)}┐`,
      "│ ChainPeer agent runtime                                                      │",
      "│ m1 · session s1                                                              │",
      "│ E:\\project                                                                   │",
      `└${"─".repeat(78)}┘`,
      "",
      "  Resumed session s1",
      "› user · hello",
      "• assistant · hi",
    ].join("\n"),
  );
});

test("startupText clips long resume preview lines", () => {
  const text = startupText({
    resume_preview: `user: ${"x".repeat(120)}`,
  });

  assert.match(text, /› user · x{69}\.\.\./);
});

test("startupText clips long cwd in the middle", () => {
  const cwd = `E:\\${"deep\\".repeat(20)}project`;
  const text = startupText({
    model: "m1",
    session_id: "s1",
    cwd,
  });
  const cwdLine = text.split("\n")[3].slice(2, -2).trim();

  assert.ok(cwdLine.length <= 78);
  assert.ok(cwdLine.startsWith("E:\\deep"));
  assert.ok(cwdLine.endsWith("\\project"));
  assert.ok(cwdLine.includes("..."));
  assert.notEqual(cwdLine, cwd);
});

test("startupText keeps banner away from terminal edge", () => {
  const originalColumns = process.stdout.columns;
  process.stdout.columns = 80;
  try {
    const firstLine = startupText({ model: "m1", session_id: "s1", cwd: "E:\\project" }).split("\n")[0];

    assert.equal(firstLine.length, 78);
  } finally {
    process.stdout.columns = originalColumns;
  }
});

test("prompt and turn status copy match the compact terminal UI", () => {
  assert.equal(
    promptText(),
    [
      "",
      "  ChainPeer input",
      "  ? shortcuts · / commands · enter send · ctrl+c interrupt/quit",
      `  ${"─".repeat(78)}`,
      "  › ",
    ].join("\n"),
  );
  assert.equal(promptPlaceholderText(), "Ask ChainPeer to do anything");
  assert.equal(answerPromptText(), "\n  › ");
  assert.equal(answerPlaceholderText(), "Type your answer");
  assert.equal(inputHintText("Ask ChainPeer to do anything"), "\x1b[sAsk ChainPeer to do anything\x1b[u");
  assert.equal(clearInputHintText(), "\x1b[K");
  assert.equal(turnStartText(), "• Working (ctrl + c to interrupt)");
  assert.equal(queuedInputText(), "• Queued follow-up input");
  assert.equal(interruptText(), "• Interrupt requested (ctrl + c again to quit)");
  assert.equal(cancelledText(), "• Interrupted session state preserved; resume with -c");
});

test("promptText includes compact session status when available", () => {
  assert.equal(
    promptText({ model: "glm-5.1", cwd: "E:\\code\\agent\\agent_base-ts-cli-process-split" }, {
      context_usage_percent: 0.125,
    }),
    [
      "",
      "  ChainPeer input",
      "  glm-5.1 · 88% context left · E:\\code\\agent\\agent_base-ts-cli-process-split",
      "  ? shortcuts · / commands · enter send · ctrl+c interrupt/quit",
      `  ${"─".repeat(78)}`,
      "  › ",
    ].join("\n"),
  );
});

test("promptText shows queue hint while a turn is running", () => {
  assert.equal(
    promptText({}, {}, { running: true }),
    [
      "",
      "  ChainPeer input",
      "  agent running · enter queue · ctrl+c interrupt · ? shortcuts",
      `  ${"─".repeat(78)}`,
      "  › ",
    ].join("\n"),
  );
});

test("promptText clips long session status", () => {
  const text = promptText({
    model: "glm-5.1-preview-with-a-very-long-name",
    cwd: `E:\\${"deep\\".repeat(20)}project`,
  }, {
    context_usage_percent: 0.25,
  });
  const statusLine = text.split("\n")[2];

  assert.ok(statusLine.length <= 80);
  assert.match(statusLine, /\.\.\.$/);
});

test("promptText keeps composer away from terminal edge", () => {
  const originalColumns = process.stdout.columns;
  process.stdout.columns = 80;
  try {
    const divider = promptText().split("\n")[3];

    assert.equal(divider.length, 78);
  } finally {
    process.stdout.columns = originalColumns;
  }
});

test("helpText renders compact shortcuts and commands", () => {
  assert.equal(
    helpText(),
    [
      "• Shortcuts",
      "  enter        send message         /              open commands",
      "  ↑ / ↓        history              ← / →          move cursor",
      "  home / end   line edges           del / backspace edit text",
      "  ctrl + c     interrupt or quit    ?              show shortcuts",
      "",
      "• Commands",
      "  /status  /sessions  /skill  /init  /plan  /compact",
      "  /model set <name>  /draft  /doctor  /config  /login",
      "  /clear  /exit",
    ].join("\n"),
  );
});

test("slashMenuText renders selectable command menu", () => {
  assert.equal(
    slashMenuText([
      { name: "help", description: "Show commands" },
      { name: "status", description: "Show session status" },
    ], 1),
    [
      "  / commands",
      "  │   /help          Show commands",
      "  │ › /status        Show session status",
      "  └ enter accept · ↑/↓ choose · esc close",
      "",
    ].join("\n"),
  );
});

test("unknownCommandText points to shortcuts help", () => {
  assert.equal(unknownCommandText(), "• Unknown command\n  └ type ? for shortcuts");
});

test("modelUsageText renders concrete model command usage", () => {
  assert.equal(modelUsageText(), "• Model command\n  └ /model set <name>");
});

test("commandResultText renders a compact success line", () => {
  assert.equal(commandResultText("Model updated: glm-5.1"), "✓ Model updated: glm-5.1");
  assert.equal(commandResultText("Compact complete", "id abc123"), "✓ Compact complete\n  └ id abc123");
  assert.match(commandResultText("x".repeat(120), "y".repeat(120)), /^✓ x{93}\.\.\.\n  └ y{93}\.\.\.$/);
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
    "• Context trimmed\n  └ CHAINPEER.md: user, project",
  );
  assert.match(
    contextBuiltLine({
      decisions: {
        chainpeer_docs_truncated: true,
        chainpeer_docs_truncated_scopes: ["x".repeat(120)],
      },
    }),
    /\n  └ CHAINPEER\.md: x{93}\.\.\.$/,
  );
});

test("toolRequestedLine shows bash command", () => {
  assert.equal(
    toolRequestedLine({
      tool_name: "bash",
      args_preview: '{"command":"date"}',
    }),
    "• Running command\n  └ date",
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
  assert.equal(toolStartedLine({ tool_name: "bash" }), "• Running command");
  assert.equal(toolStartedLine({ tool_name: "bash_output" }), "• Running output");
  assert.equal(toolStartedLine({ tool_name: "web_search" }), "• Calling web search");
  assert.equal(toolStartedLine({ tool_name: "custom_tool" }), "• Calling custom tool");
});

test("toolResultLine renders compact success state", () => {
  assert.equal(
    toolResultLine({
      tool_name: "bash",
      status: "completed",
      duration_ms: 1250,
    }),
    "✓ Ran command in 1.25s",
  );
  assert.equal(
    toolResultLine({
      tool_name: "view_image",
      status: "completed",
      duration_ms: 20,
    }),
    "✓ Called image in 20ms",
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
    "× command failed in 50ms (Timeout)\n  └ command timed out try again",
  );
});

test("toolProgressLine renders compact progress messages", () => {
  assert.equal(
    toolProgressLine({
      tool_name: "bash",
      payload: { message: "waiting\nfor output" },
    }),
    "• command\n  └ waiting for output",
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
    "• Context 51% left · cache 81.4% · output 2.1k",
  );
  assert.equal(
    tokenStatsLine({
      stats: {
        input_tokens: 1200,
        effective_context_window_tokens: 4000,
      },
    }),
    "• Context 1.2k/4.0k",
  );
  assert.equal(
    tokenStatsLine({
      stats: {
        context_usage_percent: 0.2,
        cache_hit_rate: 0,
        output_tokens: 0,
      },
    }),
    "• Context 80% left · cache 0.0% · output 0",
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
  assert.equal(
    questionText({ question: "Pick one", options: ["A", "B"], recommended: "A" }),
    [
      "• Question 1/1",
      "  Pick one",
      "  › 1. A recommended",
      "    2. B",
      "  enter number or custom answer · ctrl + c to interrupt",
    ].join("\n"),
  );
  assert.equal(
    questionText({ question: "Explain" }),
    [
      "• Question 1/1",
      "  Explain",
      "  enter to submit answer · ctrl + c to interrupt",
    ].join("\n"),
  );
  assert.match(questionText({ question: "q".repeat(120) }), /\n  q{73}\.\.\.\n/);
  assert.match(questionText({ question: "Pick", options: ["x".repeat(120)] }), /\n    1\. x{67}\.\.\.\n/);
  assert.equal(skillLine({ skill_name: "debugging" }), "• Using skill debugging");
  assert.equal(errorLine("failed"), "× Turn failed\n  └ failed");
  assert.equal(errorLine(""), "× Turn failed");
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

test("AssistantRenderer renders markdown links as readable text", () => {
  let output = "";
  const renderer = new AssistantRenderer((text) => {
    output += text;
  }, { color: false });

  renderer.append("See [docs](https://example.com) and [**guide**](file.md).\n");
  renderer.finish();

  assert.equal(output, "See docs (https://example.com) and guide (file.md).\n");
});

test("AssistantRenderer applies ansi styles when color is enabled", () => {
  let output = "";
  const renderer = new AssistantRenderer((text) => {
    output += text;
  }, { color: true });

  renderer.append("**重点** 和 `code`");
  renderer.finish();

  assert.match(output, /\x1b\[1m重点\x1b\[0m/);
  assert.match(output, /\x1b\[1mcode\x1b\[0m/);
});

test("AssistantRenderer keeps markdown structure markers dim", () => {
  let output = "";
  const renderer = new AssistantRenderer((text) => {
    output += text;
  }, { color: true });

  renderer.append("> quote\n- item\n");
  renderer.finish();

  assert.match(output, /\x1b\[2m│ \x1b\[0mquote/);
  assert.match(output, /\x1b\[2m• \x1b\[0mitem/);
  assert.doesNotMatch(output, /\x1b\[(1;33|32)m/);
});
