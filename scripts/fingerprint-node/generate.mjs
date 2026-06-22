#!/usr/bin/env node
/**
 * Emit a coherent browser profile JSON for patchright/CloakBrowser contexts.
 * Uses Apify fingerprint-suite (header-generator + fingerprint-generator).
 */
import { FingerprintGenerator } from "fingerprint-generator";
import { HeaderGenerator } from "header-generator";

const fpGen = new FingerprintGenerator();
const headerGen = new HeaderGenerator({
  browsers: [{ name: "chrome", minVersion: 120 }],
  devices: ["desktop"],
  operatingSystems: ["windows"],
  locales: ["en-US", "en"],
});

const { fingerprint } = fpGen.getFingerprint({
  browsers: [{ name: "chrome", minVersion: 120 }],
  devices: ["desktop"],
  operatingSystems: ["windows"],
  locales: ["en-US"],
});

const headers = headerGen.getHeaders({
  browsers: [{ name: "chrome", minVersion: 120 }],
  operatingSystems: ["windows"],
  locales: ["en-US"],
});

const screen = fingerprint.screen || {};
const nav = fingerprint.navigator || {};

const payload = {
  user_agent: nav.userAgent || headers["user-agent"] || headers["User-Agent"],
  locale: nav.language?.split(",")[0] || "en-US",
  timezone_id: "America/New_York",
  viewport: {
    width: screen.width || 1920,
    height: screen.height || 1080,
  },
  extra_http_headers: headers,
};

process.stdout.write(JSON.stringify(payload));
