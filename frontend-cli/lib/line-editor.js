export function createLineEditor(initialValue = "") {
  let text = String(initialValue || "");
  let cursor = Array.from(text).length;

  return {
    input() {
      return text;
    },
    cursor() {
      return cursor;
    },
    setInput(value) {
      text = String(value || "");
      cursor = Array.from(text).length;
    },
    handleKey(chunk, key = {}) {
      if (key.name === "left") {
        return moveCursor(-1);
      }
      if (key.name === "right") {
        return moveCursor(1);
      }
      if (key.name === "home") {
        cursor = 0;
        return "move";
      }
      if (key.name === "end") {
        cursor = Array.from(text).length;
        return "move";
      }
      if (key.name === "backspace") {
        return removeBeforeCursor();
      }
      if (key.name === "delete") {
        return removeAtCursor();
      }
      if (isPrintable(chunk, key)) {
        insertText(String(chunk));
        return "edit";
      }
      return "";
    },
  };

  function moveCursor(delta) {
    const length = Array.from(text).length;
    cursor = Math.max(0, Math.min(length, cursor + delta));
    return "move";
  }

  function removeBeforeCursor() {
    if (cursor <= 0) {
      return "edit";
    }
    const chars = Array.from(text);
    chars.splice(cursor - 1, 1);
    cursor -= 1;
    text = chars.join("");
    return "edit";
  }

  function removeAtCursor() {
    const chars = Array.from(text);
    if (cursor >= chars.length) {
      return "edit";
    }
    chars.splice(cursor, 1);
    text = chars.join("");
    return "edit";
  }

  function insertText(value) {
    const chars = Array.from(text);
    const inserted = Array.from(value);
    chars.splice(cursor, 0, ...inserted);
    cursor += inserted.length;
    text = chars.join("");
  }
}

export function trailingCellWidth(text, cursor) {
  return Array.from(String(text || ""))
    .slice(cursor)
    .reduce((width, char) => width + cellWidth(char), 0);
}

function isPrintable(chunk, key) {
  return Boolean(chunk && !key.ctrl && !key.meta && String(chunk) >= " ");
}

function cellWidth(char) {
  return char.codePointAt(0) > 0xff ? 2 : 1;
}
