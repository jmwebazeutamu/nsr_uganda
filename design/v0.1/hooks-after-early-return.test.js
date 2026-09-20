/* No hook may sit below a return that can fire.
 *
 * React counts hooks per render. A component that returns early on one
 * render and reaches three more `useMemo` calls on the next crashes with
 * "Rendered more hooks than during the previous render" — #310 in a
 * production build, which is what an operator saw as "Something went
 * wrong rendering this view".
 *
 * It happened in PmtConfigurationScreen:
 *
 *     const selected = useMemo(...)        // null while loading
 *     if (!selected) { return <Loading/> }
 *     const filteredVariables = useMemo(...)   // skipped, then not
 *
 * and it was only reachable because a fabricated fallback version had
 * been removed — until then `selected` was never null, the early return
 * never fired, and the hook counts never diverged. Deleting invented
 * data makes real states reachable for the first time, and the code
 * below them has never run.
 *
 * An earlier version of this check looked only for a `return` at the
 * component's own indentation and so missed this one, which is wrapped
 * in `if (…) { … }`. It counts braces instead.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DESIGN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MANIFESTS = ["nsr-mis-console.html", "nsr-mis-admin-console.html"];

const COMPONENT = /^const\s+([A-Z]\w*)\s*=\s*.*=>\s*\{\s*$/;
const HOOK = /(?:React\.)?(use[A-Z]\w*)\s*\(/;

const shippedFiles = () => {
  const files = new Set();
  for (const manifest of MANIFESTS) {
    const html = fs.readFileSync(path.join(DESIGN, manifest), "utf8");
    for (const [, src] of html.matchAll(/src="([^"]+\.jsx)"/g)) files.add(src.replace(/^\.\//, ""));
  }
  return [...files].sort();
};

/** Strings and comments hide braces; take them out before counting. */
const strip = (line) => line
  .replace(/"(?:[^"\\]|\\.)*"/g, '""')
  .replace(/'(?:[^'\\]|\\.)*'/g, "''")
  .replace(/`(?:[^`\\]|\\.)*`/g, "``")
  .replace(/\/\/.*$/, "");

/**
 * Hooks in `file` that a return above them can skip.
 *
 * Depth 1 is the component body. A `return` at depth 1 exits. A `return`
 * at depth 2 inside an `if (…) {` opened at depth 1 also exits — that is
 * the shape this missed the first time. Returns deeper than that, or
 * inside a callback, are somebody else's control flow.
 */
export const skippableHooks = (src) => {
  const lines = src.split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const match = COMPONENT.exec(lines[i]);
    if (!match) { i += 1; continue; }
    const component = match[1];
    let depth = 1;
    let exitAt = null;
    let ifAtDepth1 = false;
    let j = i + 1;
    while (j < lines.length) {
      const clean = strip(lines[j]);
      const before = depth;
      depth += (clean.match(/\{/g) || []).length - (clean.match(/\}/g) || []).length;

      if (before === 1) {
        ifAtDepth1 = /^\s*(if|else)\b/.test(clean) && clean.includes("{");
        if (/^\s*return\b/.test(clean) && exitAt === null) exitAt = j + 1;
        else if (exitAt !== null && HOOK.test(clean)) {
          out.push({ component, line: j + 1, hook: HOOK.exec(clean)[1], exitAt });
        }
      } else if (before === 2 && ifAtDepth1 && /^\s*return\b/.test(clean) && exitAt === null) {
        exitAt = j + 1;
      }

      if (depth <= 0) break;
      j += 1;
    }
    i = j + 1;
  }
  return out;
};

describe("hooks below an early return", () => {
  const files = shippedFiles();

  it("scans the files both consoles ship", () => {
    expect(files.length).toBeGreaterThan(40);
  });

  it.each(files)("%s", (relative) => {
    const src = fs.readFileSync(path.join(DESIGN, relative), "utf8");
    const findings = skippableHooks(src).map(
      f => `${relative}:${f.line} ${f.hook} in ${f.component} — a return at line ${f.exitAt} can skip it`,
    );
    expect(
      findings,
      `These hooks run on some renders and not others, which React ends `
      + `with "Rendered more hooks than during the previous render":\n${findings.join("\n")}\n\n`
      + "Move the guard below every hook, and make what it guarded null-safe.",
    ).toEqual([]);
  });

  it("catches the shape that got through", () => {
    // The PmtConfigurationScreen bug, reduced. If this stops failing,
    // the scan has gone blind again and the suite above means nothing.
    const offender = [
      "const Screen = ({ x }) => {",
      "  const a = useMemo(() => 1, []);",
      "  if (!a) {",
      "    return <Empty/>;",
      "  }",
      "  const b = useMemo(() => 2, []);",
      "  return <div>{b}</div>;",
      "};",
    ].join("\n");
    const found = skippableHooks(offender);
    expect(found).toHaveLength(1);
    expect(found[0]).toMatchObject({ component: "Screen", hook: "useMemo", line: 6 });
  });

  it("does not flag a return inside a callback", () => {
    const fine = [
      "const Screen = () => {",
      "  const a = useMemo(() => {",
      "    if (!x) { return null; }",
      "    return 1;",
      "  }, []);",
      "  const b = useState(0);",
      "  return <div>{a}{b}</div>;",
      "};",
    ].join("\n");
    expect(skippableHooks(fine)).toEqual([]);
  });
});
