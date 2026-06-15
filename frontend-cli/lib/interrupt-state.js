export function sigintAction({ activeTurn, interruptRequested }) {
  if (!activeTurn) {
    return "shutdown";
  }
  return interruptRequested ? "force-shutdown" : "interrupt";
}
