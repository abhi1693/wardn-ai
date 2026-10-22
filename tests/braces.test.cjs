const assert = require("node:assert/strict");
const { test } = require("node:test");
const { spawnSync } = require("node:child_process");
const braces = require("braces");
const micromatch = require("micromatch");

test("transitive consumers resolve the bounded local braces package", () => {
  assert.equal(require("braces/package.json").name, "@devfeed/braces");
  assert.equal(require.resolve("braces"), require.resolve("../packages/braces"));
});

test("deep patterns fail safely below the upstream character cap", () => {
  for (const [open, close] of [
    ["{", "}"],
    ["(", ")"],
  ]) {
    const pattern = open.repeat(3500) + "a,b" + close.repeat(3500);
    assert.ok(pattern.length < 10000);
    for (const method of [braces, braces.parse, braces.compile, braces.expand, braces.stringify]) {
      assert.throws(() => method(pattern), { name: "SyntaxError", message: /maximum depth/ });
    }
    assert.throws(() => braces.parse(open.repeat(3500)), {
      name: "SyntaxError",
      message: /maximum depth/,
    });
  }
});

test("long malformed inputs terminate within a bounded child process", () => {
  const patterns = [
    "a".repeat(9000),
    "[".repeat(9000),
    '"' + "a".repeat(8999),
    "\\".repeat(9000),
    "\u00a0\ufeff".repeat(4500),
    "{a,b" + "x".repeat(8995),
  ];
  const result = spawnSync(
    process.execPath,
    [
      "-e",
      `const assert = require("node:assert/strict");
       const braces = require("braces");
       const patterns = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
       for (const pattern of patterns) {
         const ast = braces.parse(pattern);
         assert.equal(ast.input, pattern);
         assert.equal(ast.nodes.at(-1).type, "eos");
         assert.equal(typeof braces.stringify(ast), "string");
       }
       process.stdout.write("complete");`,
    ],
    { input: JSON.stringify(patterns), encoding: "utf8", timeout: 3000 },
  );
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "complete");
});

test("walker limits cover caller-supplied deep and cyclic ASTs", () => {
  let ast = { type: "text", value: "hello" };
  for (let depth = 0; depth < 3500; depth++) ast = { type: "root", nodes: [ast] };
  const cyclic = { type: "root", nodes: [] };
  cyclic.nodes.push(cyclic);
  for (const method of [braces.compile, braces.expand, braces.stringify]) {
    for (const input of [ast, cyclic]) {
      assert.throws(() => method(input), { name: "SyntaxError", message: /maximum depth/ });
    }
  }
});

test("normal nesting, ranges, escapes, and glob matching remain compatible", () => {
  assert.deepEqual(braces.expand("src/{web,admin}/{1..3}.js"), [
    "src/web/1.js",
    "src/web/2.js",
    "src/web/3.js",
    "src/admin/1.js",
    "src/admin/2.js",
    "src/admin/3.js",
  ]);
  assert.equal(braces.compile("{a,{b,c}}"), "(a|(b|c))");
  assert.equal(braces.stringify(braces.parse("{a,{b,c}}")), "{a,{b,c}}");
  assert.deepEqual(braces.expand("\\{a,b\\}"), ["{a,b}"]);
  assert.deepEqual(braces.expand("{".repeat(90) + "x" + "}".repeat(90)), [
    "{".repeat(90) + "x" + "}".repeat(90),
  ]);
  assert.throws(() => braces.expand("{1..2000}"), /range limit/);
  assert.deepEqual(
    micromatch(["src/web/a.ts", "src/admin/b.tsx", "docs/a.md"], "src/{web,admin}/**/*.{ts,tsx}"),
    ["src/web/a.ts", "src/admin/b.tsx"],
  );
});
