"use strict";

// Bound recursive walkers below the JavaScript engine's call-stack limit.
exports.checkDepth = (depth) => {
  if (depth > 100) {
    throw new SyntaxError("Brace nesting exceeds the maximum depth of 100");
  }
};
