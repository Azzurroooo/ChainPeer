#!/usr/bin/env node

import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { AssistantRenderer } from "../lib/assistant-renderer.js";
import { buildRuntimeEnv } from "../lib/runtime-env.js";
import { isInputClosed } from "../lib/input-errors.js";
import { sigintAction } from "../lib/interrupt-state.js";
import { startupText, toolRequestedLine, toolResultLine } from "../lib/rendering.js";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..", "..");
const python = process.env.CHAINPEER_PYTHON || "python";

let nextId = 1;
let activeTurn = false;
let interruptRequested = false;
let input = null;
let runtimeClosing = false;
const pending = new Map();
const announcedTools = new Set();
const assistantRenderer = new AssistantRenderer((text) => process.stdout.write(text));
let runtimeStdoutBuffer = "";

const runtime = spawn(
  python,
  ["-m", "agent.interfaces.runtime_server.stdio", ...process.argv.slice(2)],
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
  process.stderr.write(chunk);
});

runtime.on("exit", (code, signal) => {
  for (const { reject } of pending.values()) {
    reject(new Error(`Runtime exited with ${signal || code}`));
  }
  pending.clear();
  process.exitCode = code ?? 1;
  if (input) {
    input.close();
  }
});

process.on("SIGINT", handleSigint);

try {
  const info = await request("initialize");
  input = createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  input.on("SIGINT", handleSigint);
  console.log(startupText(info));
  await promptLoop();
} catch (error) {
  closeAssistant();
  if (!isInputClosed(error)) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
} finally {
  closeRuntime();
}

async function promptLoop() {
  while (true) {
    const text = (await ask("\nYou > ")).trim();
    if (!text) {
      continue;
    }
    if (await handleCommand(text)) {
      continue;
    }
    activeTurn = true;
    console.log("\nAgent:");
    try {
      await request("turn.start", { input: text });
    } finally {
      activeTurn = false;
      interruptRequested = false;
      closeAssistant();
    }
  }
}

async function handleCommand(text) {
  if (!text.startsWith("/")) {
    return false;
  }
  const [command, ...args] = text.slice(1).split(/\s+/);
  if (command === "exit" || command === "quit") {
    await shutdownRuntime();
    process.exit(0);
  }
  if (command === "clear") {
    console.clear();
    return true;
  }
  if (command === "compact") {
    const result = await request("compact");
    console.log(`Compact complete: ${result.id || "unknown"}`);
    return true;
  }
  if (command === "model" && args[0] === "set" && args[1]) {
    await request("model.set", { model: args[1] });
    console.log(`Model updated: ${args[1]}`);
    return true;
  }
  console.log("Unknown command.");
  return true;
}

function request(method, params = {}) {
  const id = nextId++;
  runtime.stdin.write(JSON.stringify({ id, method, params }) + "\n");
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
  });
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
    void renderEvent(message.event);
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
  switch (event.type) {
    case "assistant_delta":
      assistantRenderer.append(event.text || "");
      return;
    case "tool_requested":
      closeAssistant();
      if (event.tool_call_id) {
        announcedTools.add(event.tool_call_id);
      }
      console.log(toolRequestedLine(event));
      return;
    case "tool_call_started":
      closeAssistant();
      if (event.tool_call_id && announcedTools.has(event.tool_call_id)) {
        return;
      }
      console.log(`[tool] ${event.tool_name} started`);
      return;
    case "tool_result":
      closeAssistant();
      console.log(toolResultLine(event));
      return;
    case "skill_activated":
      closeAssistant();
      console.log(`[skill] ${event.skill_name}`);
      return;
    case "user_question_requested":
      await answerQuestion(event);
      return;
    case "turn_failed":
      closeAssistant();
      console.log(`[error] ${event.error}`);
      return;
    case "turn_cancelled":
      closeAssistant();
      console.log("[User Interrupted: Session state preserved. You can resume later.]");
      return;
    case "turn_completed":
      closeAssistant();
      return;
    default:
      return;
  }
}

async function answerQuestion(event) {
  closeAssistant();
  console.log(event.question || "Input required");
  for (const [index, option] of (event.options || []).entries()) {
    const suffix = option === event.recommended ? " (recommended)" : "";
    console.log(`${index + 1}. ${option}${suffix}`);
  }
  const raw = (await ask("Answer > ")).trim();
  const answer = selectAnswer(raw, event.options || []);
  await request("user_question.respond", {
    tool_call_id: event.tool_call_id,
    answer,
  });
}

function selectAnswer(raw, options) {
  const index = Number(raw);
  if (Number.isInteger(index) && index >= 1 && index <= options.length) {
    return options[index - 1];
  }
  return raw;
}

function ask(prompt) {
  if (!input) {
    return Promise.reject(new Error("Input is not available"));
  }
  return new Promise((resolve, reject) => {
    const onClose = () => reject(new Error("Input closed"));
    input.once("close", onClose);
    input.question(prompt, (answer) => {
      input.off("close", onClose);
      resolve(answer);
    });
  });
}

function handleSigint() {
  const action = sigintAction({ activeTurn, interruptRequested });
  if (action === "interrupt") {
    interruptRequested = true;
    closeAssistant();
    console.log("\n[User Interrupted: cancelling turn...]");
    void request("turn.interrupt").catch(() => {});
    return;
  }
  if (action === "shutdown") {
    closeRuntime();
  }
}

function closeAssistant() {
  assistantRenderer.finish();
}

function closeRuntime() {
  if (runtimeClosing) {
    return;
  }
  runtimeClosing = true;
  if (runtime.exitCode === null && !runtime.killed && runtime.stdin.writable) {
    runtime.stdin.end(JSON.stringify({ id: nextId++, method: "shutdown", params: {} }) + "\n");
  }
  if (input) {
    input.close();
  }
}

async function shutdownRuntime() {
  if (runtimeClosing) {
    return;
  }
  runtimeClosing = true;
  try {
    await request("shutdown");
  } catch {
    runtime.kill();
  } finally {
    if (runtime.stdin.writable) {
      runtime.stdin.end();
    }
    if (input) {
      input.close();
    }
  }
}
