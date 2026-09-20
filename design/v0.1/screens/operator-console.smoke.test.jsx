/* Every screen in the operator console opens without crashing. See
 * console-smoke-harness.js for what this does and why. */

import { afterAll, beforeAll, describe, it } from "vitest";
import { smokeTest } from "../console-smoke-harness.js";

smokeTest({ manifest: "nsr-mis-console.html", describe, beforeAll, afterAll, it });
