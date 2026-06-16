import assert from "node:assert/strict";
import test from "node:test";

import { createSlashMenuState } from "../lib/slash-menu-state.js";

const commands = [
  { name: "status", description: "Show status" },
  { name: "sessions", description: "List sessions" },
  { name: "clear", description: "Clear screen" },
];

test("slash menu opens only for a slash command prefix", () => {
  const state = createSlashMenuState(commands);

  assert.equal(state.handleKey("/", {}), true);
  assert.deepEqual(state.matches().map((command) => command.name), ["status", "sessions", "clear"]);

  assert.equal(state.handleKey("s", {}), true);
  assert.deepEqual(state.matches().map((command) => command.name), ["status", "sessions"]);

  assert.equal(state.handleKey(" ", {}), true);
  assert.deepEqual(state.matches(), []);
});

test("slash menu arrows select commands without changing input text", () => {
  const state = createSlashMenuState(commands);
  state.setInput("/");

  assert.equal(state.input(), "/");
  assert.equal(state.selectedCommand().name, "status");

  assert.equal(state.handleKey("", { name: "down" }), true);
  assert.equal(state.input(), "/");
  assert.equal(state.selectedCommand().name, "sessions");

  assert.equal(state.handleKey("", { name: "up" }), true);
  assert.equal(state.input(), "/");
  assert.equal(state.selectedCommand().name, "status");
});

test("slash menu keeps selection when input is synced unchanged", () => {
  const state = createSlashMenuState(commands);
  state.setInput("/");
  state.handleKey("", { name: "down" });

  state.setInput("/");

  assert.equal(state.selectedCommand().name, "sessions");
});

test("slash menu escape dismisses immediately and typing reopens it", () => {
  const state = createSlashMenuState(commands);
  state.setInput("/");

  assert.equal(state.handleKey("", { name: "escape" }), true);
  assert.deepEqual(state.matches(), []);
  assert.equal(state.input(), "/");

  assert.equal(state.handleKey("s", {}), true);
  assert.equal(state.input(), "/s");
  assert.deepEqual(state.matches().map((command) => command.name), ["status", "sessions"]);
});

test("slash menu ignores modified keypresses", () => {
  const state = createSlashMenuState(commands);
  state.setInput("/");

  assert.equal(state.handleKey("x", { ctrl: true }), false);
  assert.equal(state.input(), "/");
});
