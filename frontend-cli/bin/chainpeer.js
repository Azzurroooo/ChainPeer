#!/usr/bin/env node

import { spawn } from "node:child_process";
import { createInterface, emitKeypressEvents } from "node:readline";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { AssistantRenderer } from "../lib/assistant-renderer.js";
import { createAssistantStreamBuffer } from "../lib/assistant-stream-buffer.js";
import { createLineEditor, trailingCellWidth } from "../lib/line-editor.js";
import { buildRuntimeEnv } from "../lib/runtime-env.js";
import { createInputHistory } from "../lib/input-history.js";
import { isInputClosed } from "../lib/input-errors.js";
import { sigintAction } from "../lib/interrupt-state.js";
import { createSlashMenuState } from "../lib/slash-menu-state.js";
import {
  answerPromptText,
  answerPlaceholderText,
  cancelledText,
  contextBuiltLine,
  errorLine,
  helpText,
  assistantHeaderText,
  inputHintText,
  interruptText,
  outputBlockText,
  promptActivityLine,
  promptPlaceholderText,
  promptText,
  questionText,
  queuedInputText,
  slashMenuText,
  skillLine,
  startupText,
  toolProgressLine,
  toolRequestedLine,
  toolResultLine,
  toolStartedLine,
  turnCompletedLine,
  userInputText,
} from "../lib/rendering.js";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..", "..");
const python = process.env.CHAINPEER_PYTHON || "python";
const runtimeBootstrap = [
  "import os, runpy, sys",
  `repo = os.path.abspath(${JSON.stringify(repoRoot)})`,
  "cwd = os.path.abspath(os.getcwd())",
  "blocked = {os.path.normcase(repo), os.path.normcase(cwd)}",
  "sys.path = [repo] + [p for p in sys.path if p and os.path.normcase(os.path.abspath(p)) not in blocked]",
  "runpy.run_module('agent.interfaces.runtime_server.stdio', run_name='__main__')",
].join("; ");

let nextId = 1;
let activeTurn = false;
let interruptRequested = false;
let input = null;
let inputActive = false;
let runtimeClosing = false;
let runtimeKillTimer = null;
let processExitTimer = null;
let cancelActiveInput = null;
const pending = new Map();
const announcedTools = new Set();
let sessionInfo = {};
let latestStats = {};
let slashCommands = [];
let turnTools = { completed: 0, failed: 0 };
let promptPaused = false;
let pendingInputPrefill = "";
let queuedTurns = 0;
let turnQueue = Promise.resolve();
let redrawActiveInput = null;
let redrawActiveActivity = null;
let suspendActiveInput = null;
let assistantOutputLineOpen = false;
let assistantHeaderShown = false;
let outputStarted = false;
let activityFrame = 0;
let activityTimer = null;
let activityStartedAt = 0;
const promptResumeWaiters = [];
const assistantStreamBuffer = createAssistantStreamBuffer();
const assistantRenderer = new AssistantRenderer((text) => writeOutput(text));
const inputHistory = createInputHistory();
let runtimeStdoutBuffer = "";

const runtime = spawn(
  python,
  ["-c", runtimeBootstrap, ...process.argv.slice(2)],
  {
    cwd: process.cwd(),
    env: buildRuntimeEnv(repoRoot),
    stdio: ["pipe", "pipe", "pipe"],
  },
);

runtime.stdout.setEncoding("utf8");
runtime.stdout.on("data", (chunk) => {
  runtimeStdoutBuffer += chunk;
  const lines = runtimeStdoutBuffer.split(/\r?\n/);
  runtimeStdoutBuffer = lines.pop() || "";
  for (const line of lines) {
    if (line) {
      receive(line);
    }
  }
});

runtime.stderr.on("data", (chunk) => {
  writeErrorOutput(chunk);
});

runtime.on("exit", (code, signal) => {
  clearRuntimeKillTimer();
  for (const { reject } of pending.values()) {
    reject(new Error(`Runtime exited with ${signal || code}`));
  }
  pending.clear();
  process.exitCode = runtimeClosing ? 0 : code ?? 1;
  closeInput();
  if (runtimeClosing) {
    scheduleProcessExit(process.exitCode ?? 0, 0);
  }
});

process.on("SIGINT", handleSigint);

try {
  const info = await request("initialize");
  sessionInfo = { cwd: process.cwd(), ...(info || {}) };
  slashCommands = normalizeSlashCommands(info?.slash_commands);
  if (process.stdin.isTTY) {
    emitKeypressEvents(process.stdin);
    process.stdin.on("keypress", handleKeypress);
  } else {
    input = createInterface({
      input: process.stdin,
      output: process.stdout,
      historySize: 100,
      removeHistoryDuplicates: true,
    });
    process.stdin.on("data", handleStdinData);
  }
  resumeInput();
  logOutput(startupText(info));
  await promptLoop();
} catch (error) {
  closeAssistant();
  if (!isInputClosed(error)) {
    writeErrorOutput(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
} finally {
  closeRuntime();
}

async function promptLoop() {
  while (!runtimeClosing) {
    await waitForPromptResume();
    if (runtimeClosing) {
      return;
    }
    const text = (await ask(mainPromptText, promptPlaceholderText())).trim();
    if (runtimeClosing) {
      return;
    }
    if (!text) {
      continue;
    }
    if (await handleCommand(text)) {
      continue;
    }
    submitTurn(text);
  }
}

async function handleCommand(text) {
  if (text === "?") {
    logOutput(helpText(slashCommands));
    return true;
  }
  if (!text.startsWith("/")) {
    return false;
  }
  await runSlashCommand(text);
  return true;
}

async function runSlashCommand(text) {
  const result = await request("slash.execute", { input: text });
  if (result.clear_screen) {
    withSuspendedPrompt(() => console.clear());
  }
  if (result.text) {
    logOutput(result.text);
  }
  if (result.input_prefill) {
    pendingInputPrefill = result.input_prefill;
  }
  if (result.run_turn_input) {
    submitTurn(result.run_turn_input, {
      transient_system_messages: result.transient_system_messages,
    });
  }
  if (result.should_exit) {
    await shutdownRuntime();
    process.exit(0);
  }
}

function submitTurn(text, extra = {}) {
  const wasRunning = activeTurn || queuedTurns > 0;
  if (wasRunning) {
    logOutput(queuedInputText(text));
  }
  queuedTurns += 1;
  if (!wasRunning) {
    refreshInputState();
  }
  const task = turnQueue.then(
    () => runQueuedTurn(text, extra),
    () => runQueuedTurn(text, extra),
  );
  turnQueue = task.catch((error) => {
    if (!runtimeClosing) {
      writeErrorOutput(`${error instanceof Error ? error.message : String(error)}\n`);
    }
  });
}

function inputState() {
  const running = activeTurn || queuedTurns > 0;
  return {
    running,
    frame: activityFrame,
    elapsedMs: running ? Date.now() - activityStartedAt : 0,
  };
}

function mainPromptText() {
  return promptText(sessionInfo, latestStats, inputState());
}

function refreshInputState() {
  updateActivityTimer();
  redrawInput();
}

function redrawInput() {
  if (inputActive && process.stdout.isTTY && !runtimeClosing && redrawActiveInput) {
    withTerminalCursorHidden(() => redrawActiveInput());
  }
}

function updateActivityTimer() {
  if (activeTurn || queuedTurns > 0) {
    if (!activityStartedAt) {
      activityStartedAt = Date.now();
    }
    if (activityTimer) {
      return;
    }
    activityTimer = setInterval(() => {
      activityFrame += 1;
      if (inputActive && process.stdout.isTTY && !runtimeClosing && redrawActiveActivity) {
        withTerminalCursorHidden(() => redrawActiveActivity());
      }
    }, 300);
    activityTimer.unref?.();
    return;
  }
  clearActivityTimer();
}

function clearActivityTimer() {
  if (!activityTimer) {
    return;
  }
  clearInterval(activityTimer);
  activityTimer = null;
  activityFrame = 0;
  activityStartedAt = 0;
}

async function runQueuedTurn(text, extra = {}) {
  queuedTurns = Math.max(0, queuedTurns - 1);
  if (runtimeClosing) {
    return;
  }
  activeTurn = true;
  assistantHeaderShown = false;
  resetTurnTools();
  resumeInput();
  try {
    await request("turn.start", { input: text, ...extra });
  } finally {
    activeTurn = false;
    interruptRequested = false;
    closeAssistant();
    refreshInputState();
  }
}

function request(method, params = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    if (!runtime.stdin.writable || runtime.destroyed) {
      reject(new Error("Runtime stdin is closed"));
      return;
    }
    pending.set(id, { resolve, reject });
    runtime.stdin.write(JSON.stringify({ id, method, params }) + "\n", (error) => {
      if (!error) {
        return;
      }
      pending.delete(id);
      reject(error);
    });
  });
}

function logOutput(text) {
  flushAssistantText(assistantStreamBuffer.flush(), { redraw: true });
  withSuspendedPrompt(() => {
    closeOpenAssistantOutputLine();
    process.stdout.write(outputBlockText(text, outputStarted));
    outputStarted = true;
  });
}

function writeOutput(text) {
  const holdPartialLine = inputActive && process.stdout.isTTY;
  flushAssistantText(assistantStreamBuffer.push(text, holdPartialLine));
}

function flushAssistantText(text = "", options = {}) {
  const output = String(text || "");
  if (!output) {
    return;
  }
  withSuspendedPrompt(() => {
    writeAssistantHeader();
    process.stdout.write(output);
    assistantOutputLineOpen = output ? !output.endsWith("\n") : assistantOutputLineOpen;
  }, { redraw: options.redraw !== false });
}

function writeUserInput(text) {
  flushAssistantText(assistantStreamBuffer.flush(), { redraw: false });
  closeOpenAssistantOutputLine();
  const line = userInputText(text);
  process.stdout.write(line ? outputBlockText(line, outputStarted) : "\n");
  outputStarted = true;
}

function writeErrorOutput(text) {
  flushAssistantText(assistantStreamBuffer.flush(), { redraw: true });
  withSuspendedPrompt(() => process.stderr.write(String(text || "")));
}

function withSuspendedPrompt(action, options = {}) {
  const shouldRedraw =
    inputActive && process.stdout.isTTY && !runtimeClosing && suspendActiveInput && redrawActiveInput;
  if (!shouldRedraw) {
    action();
    return;
  }
  withTerminalCursorHidden(() => {
    suspendActiveInput();
    try {
      action();
    } finally {
      if (options.redraw !== false) {
        redrawActiveInput();
      }
    }
  });
}

function withTerminalCursorHidden(action) {
  process.stdout.write("\x1b[?25l");
  try {
    action();
  } finally {
    process.stdout.write("\x1b[?25h");
  }
}

function closeOpenAssistantOutputLine() {
  if (!assistantOutputLineOpen) {
    return;
  }
  process.stdout.write("\n");
  assistantOutputLineOpen = false;
}

function writeAssistantHeader() {
  if (assistantHeaderShown) {
    return;
  }
  process.stdout.write(outputBlockText(assistantHeaderText(), outputStarted));
  outputStarted = true;
  assistantHeaderShown = true;
}

function receive(line) {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    return;
  }
  if (message.kind === "response") {
    finishRequest(message);
    return;
  }
  if (message.kind === "event") {
    void renderEvent(message.event).catch((error) => {
      if (!runtimeClosing) {
        writeErrorOutput(`${error instanceof Error ? error.message : String(error)}\n`);
      }
    });
  }
}

function finishRequest(message) {
  const callbacks = pending.get(message.id);
  if (!callbacks) {
    return;
  }
  pending.delete(message.id);
  if (message.error) {
    callbacks.reject(new Error(message.error.message || "Runtime request failed"));
  } else {
    callbacks.resolve(message.result);
  }
}

async function renderEvent(event) {
  if (runtimeClosing) {
    return;
  }
  switch (event.type) {
    case "assistant_delta":
      assistantRenderer.append(event.text || "");
      return;
    case "context_built": {
      const line = contextBuiltLine(event);
      if (line) {
        closeAssistant();
        logOutput(line);
      }
      return;
    }
    case "tool_requested":
      closeAssistant();
      if (event.tool_call_id) {
        announcedTools.add(event.tool_call_id);
      }
      logOutput(toolRequestedLine(event));
      return;
    case "tool_call_started":
      closeAssistant();
      if (event.tool_call_id && announcedTools.has(event.tool_call_id)) {
        return;
      }
      logOutput(toolStartedLine(event));
      return;
    case "tool_result":
      closeAssistant();
      recordToolResult(event);
      logOutput(toolResultLine(event));
      return;
    case "tool_progress": {
      closeAssistant();
      const line = toolProgressLine(event);
      if (line) {
        logOutput(line);
      }
      return;
    }
    case "token_stats_updated":
      closeAssistant();
      latestStats = event.stats && typeof event.stats === "object" ? event.stats : {};
      if (!activeTurn && queuedTurns === 0) {
        redrawInput();
      }
      return;
    case "skill_activated":
      closeAssistant();
      logOutput(skillLine(event));
      return;
    case "user_question_requested":
      await answerQuestion(event);
      return;
    case "turn_failed":
      closeAssistant();
      logOutput(errorLine(event.error));
      return;
    case "turn_cancelled":
      closeAssistant();
      logOutput(cancelledText());
      return;
    case "turn_completed":
      closeAssistant();
      logOutput(turnCompletedLine(event, turnTools));
      resetTurnTools();
      return;
    default:
      return;
  }
}

function recordToolResult(event) {
  if (event.status === "failed") {
    turnTools.failed += 1;
    return;
  }
  turnTools.completed += 1;
}

function resetTurnTools() {
  turnTools = { completed: 0, failed: 0 };
}

async function answerQuestion(event) {
  pausePrompt();
  closeAssistant();
  logOutput(questionText(event));
  try {
    const raw = (await ask(answerPromptText(), answerPlaceholderText())).trim();
    if (interruptRequested || runtimeClosing) {
      return;
    }
    const answer = selectAnswer(raw, event.options || []);
    await request("user_question.respond", {
      tool_call_id: event.tool_call_id,
      answer,
    });
  } finally {
    resumePrompt();
  }
}

function selectAnswer(raw, options) {
  const index = Number(raw);
  if (Number.isInteger(index) && index >= 1 && index <= options.length) {
    return options[index - 1];
  }
  return raw;
}

function ask(prompt, placeholder = "") {
  const currentPrompt = promptValue(prompt);
  if (!process.stdout.isTTY) {
    if (!input) {
      return Promise.reject(new Error("Input is not available"));
    }
    return askLine(currentPrompt);
  }
  if (!placeholder || placeholder === answerPlaceholderText()) {
    return askTtyLine(currentPrompt);
  }
  return askTtyPrompt(prompt, placeholder);
}

function askLine(prompt) {
  return new Promise((resolve, reject) => {
    const cleanup = (resume = true) => {
      inputActive = false;
      input.off("close", onClose);
      if (cancelActiveInput === onCancel) {
        cancelActiveInput = null;
      }
      if (resume) {
        resumeInput();
      }
    };
    const onClose = () => {
      cleanup(false);
      reject(new Error("Input closed"));
    };
    const onCancel = () => {
      cleanup();
      resolve("");
    };
    input.once("close", onClose);
    cancelActiveInput = onCancel;
    inputActive = true;
    input.question(prompt, (answer) => {
      cleanup();
      resolve(answer);
    });
    applyInputPrefill();
  });
}

function askTtyLine(prompt) {
  process.stdout.write(prompt);
  return new Promise((resolve) => {
    const editor = createLineEditor();
    const cleanup = () => {
      inputActive = false;
      redrawActiveInput = null;
      redrawActiveActivity = null;
      suspendActiveInput = null;
      process.stdin.off("keypress", onKeypress);
      if (cancelActiveInput === onCancel) {
        cancelActiveInput = null;
      }
      resumeInput();
    };
    const onKeypress = (chunk, key = {}) => {
      if (isCtrlC(key)) {
        return;
      }
      if (key.name === "return" || key.name === "enter") {
        cleanup();
        process.stdout.write("\n");
        resolve(editor.input());
        return;
      }
      if (editor.handleKey(chunk, key)) {
        render();
      }
    };
    const onCancel = () => {
      cleanup();
      resolve("");
    };
    const render = () => {
      closeOpenAssistantOutputLine();
      process.stdout.write("\r\x1b[K");
      process.stdout.write(`${prompt}${editor.input()}`);
      const tailWidth = trailingCellWidth(editor.input(), editor.cursor());
      if (tailWidth) {
        process.stdout.write(`\x1b[${tailWidth}D`);
      }
    };
    cancelActiveInput = onCancel;
    inputActive = true;
    redrawActiveInput = (prefill) => {
      if (typeof prefill === "string") {
        editor.setInput(prefill);
      }
      render();
    };
    suspendActiveInput = () => process.stdout.write("\r\x1b[K");
    process.stdin.on("keypress", onKeypress);
    render();
    applyInputPrefill();
  });
}

function askTtyPrompt(prompt, placeholder) {
  return new Promise((resolve) => {
    const editor = createLineEditor(pendingInputPrefill);
    const menuState = createSlashMenuState(slashCommands);
    let rendered = false;
    let promptRowsAbove = 0;
    let promptRowsBelow = 0;
    pendingInputPrefill = "";
    const cleanup = () => {
      inputActive = false;
      process.stdin.off("keypress", onKeypress);
      clearPromptBlock();
      if (cancelActiveInput === onCancel) {
        cancelActiveInput = null;
      }
      redrawActiveInput = null;
      redrawActiveActivity = null;
      suspendActiveInput = null;
      resumeInput();
    };
    const onKeypress = (chunk, key = {}) => {
      if (isCtrlC(key)) {
        return;
      }
      if (key.name === "return" || key.name === "enter") {
        syncMenu();
        const command = menuState.selectedCommand();
        const answer = command ? `/${command.name}` : editor.input();
        inputHistory.add(answer);
        cleanup();
        writeUserInput(answer);
        resolve(answer);
        return;
      }
      const menuOpen = syncMenu().length > 0;
      if (menuOpen) {
        if (key.name === "escape" || key.name === "up" || key.name === "down") {
          if (menuState.handleKey("", key)) {
            renderPrompt();
            return;
          }
        }
      } else if (key.name === "up") {
        editor.setInput(inputHistory.previous(editor.input()));
        renderPrompt();
        return;
      } else if (key.name === "down") {
        editor.setInput(inputHistory.next(editor.input()));
        renderPrompt();
        return;
      }
      const editResult = editor.handleKey(chunk, key);
      if (editResult) {
        if (editResult === "edit") {
          inputHistory.reset();
        }
        renderPrompt();
      }
    };
    const onCancel = () => {
      cleanup();
      resolve("");
    };
    process.stdin.resume();
    process.stdin.on("keypress", onKeypress);
    cancelActiveInput = onCancel;
    inputActive = true;
    redrawActiveInput = (prefill) => {
      if (typeof prefill === "string") {
        editor.setInput(prefill);
      }
      renderPrompt();
    };
    redrawActiveActivity = renderActivityLine;
    suspendActiveInput = clearPromptBlock;
    renderPrompt();

    function renderPrompt() {
      const block = splitPromptBlock(promptValue(prompt));
      closeOpenAssistantOutputLine();
      clearPromptBlock();
      promptRowsAbove = countLineBreaks(block.leading);
      process.stdout.write(block.leading);
      writeInputLine(block.prefix);
      promptRowsBelow = writeRowsBelow(block.trailing);
      restoreInputCursor(block.prefix);
      rendered = true;
    }

    function renderActivityLine() {
      const line = promptActivityLine(inputState());
      const rowsAbove = promptRowsAbove - 1;
      if (!rendered || !line || rowsAbove <= 0) {
        return;
      }
      process.stdout.write(`\x1b7\x1b[${rowsAbove}A\r\x1b[K${line}\x1b8`);
    }

    function clearPromptBlock() {
      if (!rendered) {
        return;
      }
      if (promptRowsAbove) {
        process.stdout.write(`\x1b[${promptRowsAbove}A`);
      }
      process.stdout.write("\r\x1b[J");
      rendered = false;
      promptRowsBelow = 0;
    }

    function writeInputLine(prefix) {
      process.stdout.write("\r\x1b[K");
      process.stdout.write(prefix);
      process.stdout.write(editor.input() || inputHintText(placeholder));
    }

    function restoreInputCursor(prefix) {
      if (promptRowsBelow) {
        process.stdout.write(`\x1b[${promptRowsBelow}A`);
      }
      process.stdout.write("\r");
      const width = promptPrefixWidth(prefix) + cursorCellWidth(editor.input(), editor.cursor());
      if (width) {
        process.stdout.write(`\x1b[${width}C`);
      }
    }

    function writeRowsBelow(trailing) {
      let rows = writeMenu();
      const text = String(trailing || "");
      if (text) {
        process.stdout.write(`\r\n${text}`);
        rows += lineCount(text);
      }
      return rows;
    }

    function writeMenu() {
      const menu = slashMenuText(syncMenu(), menuState.selectedIndex()).trimEnd();
      if (!menu) {
        return 0;
      }
      process.stdout.write(`\r\n${menu}`);
      return lineCount(menu);
    }

    function syncMenu() {
      menuState.setInput(editor.input());
      return menuState.matches();
    }
  });
}

function countLineBreaks(text) {
  return (String(text).match(/\n/g) || []).length;
}

function normalizeSlashCommands(commands) {
  if (!Array.isArray(commands)) {
    return [];
  }
  const items = [];
  for (const command of commands) {
    const name = singleWord(command?.name);
    if (!name) {
      continue;
    }
    const description = String(command.description || "").trim();
    items.push({ name, description });
    for (const alias of command.aliases || []) {
      const aliasName = singleWord(alias);
      if (aliasName) {
        items.push({ name: aliasName, description: `alias for /${name}` });
      }
    }
  }
  return items.sort((left, right) => left.name.localeCompare(right.name));
}

function singleWord(value) {
  const text = String(value || "").trim().toLowerCase();
  return text && !/\s/.test(text) ? text : "";
}

function pausePrompt() {
  promptPaused = true;
  cancelInput();
}

function resumePrompt() {
  promptPaused = false;
  while (promptResumeWaiters.length) {
    promptResumeWaiters.shift()();
  }
}

function waitForPromptResume() {
  if (!promptPaused) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    promptResumeWaiters.push(resolve);
  });
}

function applyInputPrefill() {
  if (!pendingInputPrefill) {
    return;
  }
  const text = pendingInputPrefill;
  pendingInputPrefill = "";
  if (redrawActiveInput) {
    redrawActiveInput(text);
    return;
  }
  input.write(text);
}

function promptValue(prompt) {
  return typeof prompt === "function" ? prompt() : prompt;
}

function splitPromptBlock(prompt) {
  const text = String(prompt || "");
  const marker = "\n  › ";
  const index = text.lastIndexOf(marker);
  if (index === -1) {
    return { leading: "", prefix: text, trailing: "" };
  }
  const inputStart = index + 1;
  const trailingStart = text.indexOf("\n", inputStart);
  if (trailingStart === -1) {
    return {
      leading: text.slice(0, inputStart),
      prefix: text.slice(inputStart),
      trailing: "",
    };
  }
  return {
    leading: text.slice(0, inputStart),
    prefix: text.slice(inputStart, trailingStart),
    trailing: text.slice(trailingStart + 1),
  };
}

function lineCount(text) {
  return String(text || "").split("\n").length;
}

function cursorCellWidth(text, cursor) {
  return Array.from(String(text || ""))
    .slice(0, cursor)
    .reduce((width, char) => width + cellWidth(char), 0);
}

function promptPrefixWidth(text) {
  return String(text || "").replace(/\x1b\[[0-9;]*m/g, "").length;
}

function cellWidth(char) {
  return char.codePointAt(0) > 0xff ? 2 : 1;
}

function handleSigint() {
  const action = sigintAction({ activeTurn, interruptRequested, runtimeClosing });
  if (action === "interrupt") {
    interruptTurn();
  } else {
    exitFromSignal();
  }
}

function interruptTurn() {
  interruptRequested = true;
  cancelInput();
  closeAssistant();
  logOutput(interruptText());
  void request("turn.interrupt").catch(() => {});
}

function handleKeypress(text, key) {
  if (isCtrlC(key)) {
    handleSigint();
  }
}

function handleStdinData(chunk) {
  if (Buffer.from(chunk).includes(3)) {
    handleSigint();
  }
}

function isCtrlC(key) {
  return Boolean(key?.ctrl && key.name === "c");
}

function exitFromSignal() {
  forceCloseRuntime();
  scheduleProcessExit(0, 0);
}

function resumeInput() {
  if (runtimeClosing) {
    return;
  }
  try {
    process.stdin.setRawMode?.(true);
    process.stdin.resume();
  } catch {
    // Ignore stdin implementations that cannot be resumed after close.
  }
}

function closeAssistant() {
  assistantRenderer.finish();
  flushAssistantText(assistantStreamBuffer.flush());
  assistantHeaderShown = false;
}

function closeRuntime() {
  if (runtimeClosing) {
    return;
  }
  runtimeClosing = true;
  clearActivityTimer();
  if (runtime.exitCode === null && !runtime.killed) {
    if (runtime.stdin.writable) {
      runtime.stdin.end(JSON.stringify({ id: nextId++, method: "shutdown", params: {} }) + "\n");
    }
    scheduleRuntimeKill();
  }
  closeInput();
}

function forceCloseRuntime() {
  runtimeClosing = true;
  clearActivityTimer();
  clearRuntimeKillTimer();
  closeInput();
  killRuntime();
}

function cancelInput() {
  const cancel = cancelActiveInput;
  cancelActiveInput = null;
  cancel?.();
}

function killRuntime() {
  if (runtime.killed || runtime.exitCode !== null) {
    return;
  }
  try {
    runtime.kill("SIGKILL");
  } catch {
    // Ignore kill races; the process may already be exiting.
  }
}

async function shutdownRuntime() {
  if (runtimeClosing) {
    return;
  }
  runtimeClosing = true;
  clearActivityTimer();
  scheduleRuntimeKill();
  try {
    await request("shutdown");
  } catch {
    killRuntime();
  } finally {
    if (runtime.stdin.writable) {
      runtime.stdin.end();
    }
    closeInput();
  }
}

function scheduleRuntimeKill() {
  clearRuntimeKillTimer();
  runtimeKillTimer = setTimeout(() => {
    killRuntime();
  }, 1500);
  runtimeKillTimer.unref?.();
}

function clearRuntimeKillTimer() {
  if (!runtimeKillTimer) {
    return;
  }
  clearTimeout(runtimeKillTimer);
  runtimeKillTimer = null;
}

function scheduleProcessExit(code, delayMs) {
  if (processExitTimer) {
    return;
  }
  process.exitCode = code;
  processExitTimer = setTimeout(() => {
    try {
      closeInput();
    } finally {
      process.exit(code);
    }
  }, delayMs);
}

function closeInput() {
  cancelInput();
  process.stdin.off("keypress", handleKeypress);
  process.stdin.off("data", handleStdinData);
  if (input) {
    const current = input;
    input = null;
    try {
      current.close();
    } catch {
      // Ignore readline close races during signal shutdown.
    }
  }
  try {
    process.stdin.setRawMode?.(false);
  } catch {
    // Some stdin implementations expose setRawMode but reject after close.
  }
  process.stdin.pause();
}
