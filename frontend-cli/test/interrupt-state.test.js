import assert from "node:assert/strict";
import test from "node:test";

import { sigintAction } from "../lib/interrupt-state.js";

test("sigintAction interrupts active turn once", () => {
  assert.equal(sigintAction({ activeTurn: true, interruptRequested: false }), "interrupt");
  assert.equal(sigintAction({ activeTurn: true, interruptRequested: true }), "ignore");
});

test("sigintAction shuts down outside active turn", () => {
  assert.equal(sigintAction({ activeTurn: false, interruptRequested: false }), "shutdown");
});
