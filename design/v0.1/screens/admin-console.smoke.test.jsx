/* Every screen in the Admin Console opens without crashing. See
 * console-smoke-harness.js for what this does and why. */

import { afterAll, beforeAll, describe, it } from "vitest";
import { smokeTest } from "../console-smoke-harness.js";

smokeTest({ manifest: "nsr-mis-admin-console.html", describe, beforeAll, afterAll, it });
