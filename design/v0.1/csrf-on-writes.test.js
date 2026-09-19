/* Guard: every write the console makes must carry a CSRF token.
 *
 * Django's SessionAuthentication is first in
 * DEFAULT_AUTHENTICATION_CLASSES, so CSRF is enforced on every unsafe
 * method. A `fetch` with `method: "POST"` and no `X-CSRFToken` header is
 * a 403 for every signed-in operator — the button simply does nothing.
 *
 * That is not theoretical. "Re-run gates" on the DIH queue shipped
 * without the header, in both its single and bulk forms, along with
 * archive, inline edit, the DRS estimate calls and the DQA validation
 * panel: seven writes, all 403, none of them noticed, because the
 * handlers reported failure as a count rather than a reason.
 *
 * Backend tests do not catch it — DRF's APIClient with
 * `force_authenticate` bypasses CSRF entirely, so the endpoint passes
 * its own tests while the button that calls it cannot work. This scans
 * the source the console actually ships.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DESIGN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MANIFESTS = ["nsr-mis-console.html", "nsr-mis-admin-console.html"];
const UNSAFE = /method:\s*["'](POST|PUT|PATCH|DELETE)["']/;

const shippedFiles = () => {
  const files = new Set();
  for (const manifest of MANIFESTS) {
    const html = fs.readFileSync(path.join(DESIGN, manifest), "utf8");
    for (const [, src] of html.matchAll(/src="([^"]+\.jsx)"/g)) {
      files.add(src.replace(/^\.\//, ""));
    }
  }
  return [...files].sort();
};

/**
 * Every `fetch(...)` options object in the source, as raw text.
 *
 * Deliberately crude: it reads the source rather than executing it, so
 * a call cannot hide behind a helper the test forgot to mock. Calls
 * routed through `nsrApi` carry the header from the client and never
 * match, because they have no options object of their own.
 */
const fetchOptionBlocks = (src) => {
  const blocks = [];
  const re = /fetch\s*\(/g;
  let match;
  while ((match = re.exec(src)) !== null) {
    // Walk to the options object: the first `{` after the URL argument.
    let i = re.lastIndex;
    let depth = 0;
    let start = -1;
    for (; i < src.length && i < re.lastIndex + 1200; i += 1) {
      const c = src[i];
      if (c === "{" && start === -1) { start = i; depth = 1; continue; }
      if (start === -1) {
        if (c === ")") break;           // fetch(url) with no options
        continue;
      }
      if (c === "{") depth += 1;
      else if (c === "}") {
        depth -= 1;
        if (depth === 0) { blocks.push({ text: src.slice(start, i + 1), index: match.index }); break; }
      }
    }
  }
  return blocks;
};

describe("console writes carry a CSRF token", () => {
  const files = shippedFiles();

  it("resolves the manifests", () => {
    expect(files.length).toBeGreaterThan(40);
  });

  it.each(files)("%s", (relative) => {
    const full = path.join(DESIGN, relative);
    const src = fs.readFileSync(full, "utf8");
    const offenders = [];

    for (const block of fetchOptionBlocks(src)) {
      if (!UNSAFE.test(block.text)) continue;
      if (block.text.includes("X-CSRFToken")) continue;
      // `headers: _headers()` delegates to a helper that sets the token
      // at call time; only a literal header object can be checked here.
      // The helper itself is asserted separately below.
      if (/headers:\s*[A-Za-z_$]/.test(block.text)) continue;
      const line = src.slice(0, block.index).split("\n").length;
      const method = block.text.match(UNSAFE)[1];
      offenders.push(`${relative}:${line} ${method} without X-CSRFToken`);
    }

    expect(
      offenders,
      `These writes will 403 for every signed-in operator:\n${offenders.join("\n")}\n\n`
      + "Add \"X-CSRFToken\": <the file's csrf helper>() to the headers, or "
      + "route the call through window.nsrApi, which sets it for you.",
    ).toEqual([]);
  });
});

describe("the shared header helper", () => {
  it("sets the token, since calls delegate to it", () => {
    // The exemption above is only safe while this is true.
    const src = fs.readFileSync(path.join(DESIGN, "v0.1/data/api-client.jsx"), "utf8");
    const helper = src.slice(src.indexOf("const _headers"), src.indexOf("const nsrApi"));
    expect(helper).toContain("X-CSRFToken");
  });
});
