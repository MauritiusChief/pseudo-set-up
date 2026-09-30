#!/usr/bin/env node
"use strict";

/**
 * Endless, display-only npm installation simulator.
 *
 * Call structure:
 *   main
 *   |-- parseArgs
 *   |   `-- detectNpm
 *   |-- Terminal
 *   `-- runForever
 *       |-- NetworkState
 *       |-- dependencyOrder
 *       |-- virtualPackages
 *       |-- collectPackage
 *       |   `-- download
 *       |       `-- NetworkState.update
 *       |-- buildPackages
 *       `-- installBatch
 *
 * main owns the process lifetime; runForever chooses batches; collectPackage,
 * buildPackages and installBatch only render one stage. No package-manager
 * installation, network request or file write is performed by this script.
 */

const { execFileSync } = require("node:child_process");

/** @typedef {{name: string, version: string, sizeMb: number, dependencies: string[], native: boolean}} Package */
/** @typedef {{text: string, parts: number[]}} ParsedVersion */
/** @typedef {{package: Package, parent: string}} PackageEntry */
/** @typedef {{node: ParsedVersion, npm: ParsedVersion, loglevel: string}} Options */

const MIN_SPEED_MB_S = 0.3;
const MAX_SPEED_MB_S = 3.5;
const FRAME_MS = 150;
const LOG_LEVELS = ["error", "warn", "notice", "http", "info", "verbose"];
const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

function pkg(name, version, sizeMb, dependencies = [], native = false) {
  return { name, version, sizeMb, dependencies, native };
}

// A small, recognizable dependency graph; these are display data, not inputs
// to npm. Versions remain fixed during a run, including repeated batches.
const PACKAGES = {
  react: pkg("react", "19.1.1", 0.12),
  "react-dom": pkg("react-dom", "19.1.1", 1.3, ["react", "scheduler"]),
  scheduler: pkg("scheduler", "0.26.0", 0.09),
  vite: pkg("vite", "7.1.5", 0.82, ["rollup", "esbuild", "postcss"]),
  rollup: pkg("rollup", "4.50.1", 2.1),
  esbuild: pkg("esbuild", "0.25.9", 1.8, [], true),
  postcss: pkg("postcss", "8.5.6", 0.29, ["nanoid", "picocolors", "source-map-js"]),
  nanoid: pkg("nanoid", "3.3.11", 0.01),
  picocolors: pkg("picocolors", "1.1.1", 0.01),
  "source-map-js": pkg("source-map-js", "1.2.1", 0.06),
  typescript: pkg("typescript", "5.9.2", 4.4),
  axios: pkg("axios", "1.12.1", 0.43, ["follow-redirects", "form-data", "proxy-from-env"]),
  "follow-redirects": pkg("follow-redirects", "1.15.11", 0.04),
  "form-data": pkg("form-data", "4.0.4", 0.09, ["asynckit", "combined-stream", "mime-types"]),
  asynckit: pkg("asynckit", "0.4.0", 0.02),
  "combined-stream": pkg("combined-stream", "1.0.8", 0.02, ["delayed-stream"]),
  "delayed-stream": pkg("delayed-stream", "1.0.0", 0.01),
  "mime-types": pkg("mime-types", "2.1.35", 0.04, ["mime-db"]),
  "mime-db": pkg("mime-db", "1.52.0", 0.19),
  "proxy-from-env": pkg("proxy-from-env", "1.1.0", 0.01),
  lodash: pkg("lodash", "4.17.21", 0.32),
  chalk: pkg("chalk", "5.6.0", 0.04),
  zod: pkg("zod", "4.1.5", 0.93),
  "date-fns": pkg("date-fns", "4.1.0", 3.1),
};

const ROOT_PACKAGES = [
  "react-dom", "vite", "typescript", "axios", "lodash", "chalk", "zod", "date-fns",
];
const PREFIXES = ["swift", "cloud", "micro", "hyper", "neo", "smart", "web", "tiny", "open"];
const BODIES = ["core", "utils", "client", "bridge", "parser", "stream", "cache", "kit", "flow"];
const SUFFIXES = ["", "-js", "-next", "-tools", "-plugin", "-runtime"];

function choose(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function between(min, max) {
  return min + Math.random() * (max - min);
}

function shuffle(items) {
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Parse a one-to-three-part version for comparison without losing its CLI form.
 * @param {string} value
 * @param {string} flag - Option name used in validation errors.
 * @returns {ParsedVersion}
 */
function version(value, flag) {
  if (!/^\d+(?:\.\d+){0,2}$/.test(value)) {
    throw new Error(`${flag} must have one to three numeric parts (for example, 22.9.0)`);
  }
  const parts = value.split(".").map(Number);
  if (parts.some((part) => !Number.isSafeInteger(part))) {
    throw new Error(`${flag} contains a number that is too large`);
  }
  return { text: value, parts: [parts[0], parts[1] ?? 0, parts[2] ?? 0] };
}

function atLeast(actual, minimum) {
  for (let i = 0; i < 3; i++) {
    if (actual[i] !== minimum[i]) return actual[i] > minimum[i];
  }
  return true;
}

/**
 * Query the installed npm version, independently of the Node.js version.
 * @returns {string} The output of `npm --version`.
 * @throws {Error} If npm cannot be queried; --npm can bypass detection.
 */
function detectNpm() {
  try {
    // On Windows npm is usually a .cmd file; invoke the command interpreter
    // with a fixed query instead of passing arguments through shell: true.
    // This does not install anything or access a registry.
    const windows = process.platform === "win32";
    return execFileSync(windows ? "cmd.exe" : "npm",
      windows ? ["/d", "/s", "/c", "npm --version"] : ["--version"], {
      encoding: "utf8", timeout: 5000, windowsHide: true,
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    throw new Error("Could not detect npm; install npm or pass --npm VERSION");
  }
}

/**
 * Resolve CLI overrides and validate the simulated Node.js/npm pairing.
 * @param {string[]} argv - Arguments after the script path.
 * @returns {Options | {help: true}}
 */
function parseArgs(argv) {
  let nodeOverride;
  let npmOverride;
  let loglevel = "notice";
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") return { help: true };
    if (arg === "--loglevel" || arg.startsWith("--loglevel=")) {
      const value = arg === "--loglevel" ? argv[++i] : arg.slice("--loglevel=".length);
      if (!LOG_LEVELS.slice(2).includes(value)) {
        throw new Error(`--loglevel must be one of notice, http, info, verbose`);
      }
      loglevel = value;
    } else if (arg === "--node" || arg === "--npm") {
      const value = argv[++i];
      if (!value) throw new Error(`${arg} requires a version`);
      if (arg === "--node") nodeOverride = value;
      else npmOverride = value;
    } else {
      throw new Error(`Unknown option: ${arg}`);
    }
  }

  const node = version(nodeOverride ?? process.versions.node, "--node");
  const npm = version(npmOverride ?? detectNpm(), "--npm");
  if (!atLeast(node.parts, [18, 0, 0]) || !atLeast(npm.parts, [9, 0, 0])) {
    throw new Error("This simulator supports Node.js 18+ and npm 9+");
  }
  // Validate the known npm 10/11 engine ranges for manual overrides. Newer
  // npm majors are left open rather than guessing their future requirements.
  const npmMajor = npm.parts[0];
  const nodeMajor = node.parts[0];
  const npm10Supported = (nodeMajor === 18 && atLeast(node.parts, [18, 17, 0])) || nodeMajor >= 20;
  const npm11Supported = (nodeMajor === 20 && atLeast(node.parts, [20, 17, 0])) ||
    atLeast(node.parts, [22, 9, 0]);
  if ((npmMajor === 10 && !npm10Supported) || (npmMajor === 11 && !npm11Supported)) {
    throw new Error(`npm ${npm.text} is not compatible with Node.js ${node.text}`);
  }
  return { node, npm, loglevel };
}

/** Filter and color npm-style logs; manage an independent stderr spinner. */
class Terminal {
  constructor(loglevel) {
    this.loglevel = LOG_LEVELS.indexOf(loglevel);
    this.color = Boolean(process.stderr.isTTY) && !("NO_COLOR" in process.env);
    this.interactive = Boolean(process.stderr.isTTY);
    this.rendered = false;
    this.frame = 0;
    this.delay = null;
    this.interval = null;
  }

  paint(text, code) {
    return this.color ? `\x1b[${code}m${text}\x1b[0m` : text;
  }

  start() {
    if (!this.interactive) return;
    // npm delays the spinner to avoid flashing on commands that finish quickly.
    this.delay = setTimeout(() => {
      this.delay = null;
      this.draw();
      this.interval = setInterval(() => this.draw(), 80);
      this.interval.unref();
    }, 200);
    this.delay.unref();
  }

  draw() {
    this.clear();
    this.frame = (this.frame + 1) % SPINNER_FRAMES.length;
    process.stderr.write(SPINNER_FRAMES[this.frame]);
    this.rendered = true;
  }

  clear() {
    if (this.rendered) {
      process.stderr.write("\r\x1b[0K");
      this.rendered = false;
    }
  }

  stop() {
    clearTimeout(this.delay);
    clearInterval(this.interval);
    this.delay = null;
    this.interval = null;
    this.clear();
  }

  /** Emit levels up to the selected threshold; npm writes log records to stderr. */
  log(level, title, message) {
    if (LOG_LEVELS.indexOf(level) > this.loglevel) return;
    this.clear();
    const colors = { error: "31", warn: "33", notice: "96", http: "32", info: "36", verbose: "34" };
    const prefix = this.paint("npm", "1") + " " + this.paint(level, colors[level]);
    const label = title ? ` ${this.paint(title, "94")}` : "";
    process.stderr.write(`${prefix}${label}${message ? ` ${message}` : ""}\n`);
    if (this.interval) this.draw();
  }
}

/** Keep one drifting download speed across every package and batch. */
class NetworkState {
  constructor() {
    this.speed = between(MIN_SPEED_MB_S, MAX_SPEED_MB_S);
    this.target = between(MIN_SPEED_MB_S, MAX_SPEED_MB_S);
  }

  /** Advance the shared speed by one download frame, in MB/s. @returns {number} */
  update() {
    if (Math.random() < 0.03) this.target = between(MIN_SPEED_MB_S, MAX_SPEED_MB_S);
    this.speed = Math.max(MIN_SPEED_MB_S, Math.min(MAX_SPEED_MB_S,
      this.speed + (this.target - this.speed) * 0.08 + between(-0.06, 0.06)));
    return this.speed;
  }
}

/**
 * Walk a real root's dependency graph once, recording each package's parent.
 * @param {string} root - Name in PACKAGES.
 * @returns {PackageEntry[]} Root first, then its shuffled dependencies.
 */
function dependencyOrder(root) {
  const entries = [];
  const visited = new Set();
  function visit(name, parent = "") {
    if (visited.has(name)) return;
    visited.add(name);
    entries.push({ package: PACKAGES[name], parent });
    for (const dependency of shuffle([...PACKAGES[name].dependencies])) {
      visit(dependency, name);
    }
  }
  visit(root);
  return entries;
}

/**
 * Mix in fictional packages without changing their definitions across batches.
 * @param {number} count - Number of distinct fictional packages in this batch.
 * @param {Map<string, Package>} catalog - Process-wide virtual package catalog.
 * @param {string[]} candidates - Real packages eligible as dependencies.
 * @returns {Package[]}
 */
function virtualPackages(count, catalog, candidates) {
  const selected = new Set();
  const result = [];
  while (result.length < count) {
    const name = choose(PREFIXES) + choose(BODIES) + choose(SUFFIXES);
    if (PACKAGES[name] || selected.has(name)) continue;
    if (!catalog.has(name)) {
      const dependencies = shuffle([...candidates]).slice(0, Math.floor(between(0, 4)));
      const size = Math.random() < 0.8 ? between(0.02, 0.7) : between(0.7, 3.5);
      catalog.set(name, pkg(name, `${choose([0, 0, 1, 2, 3])}.${Math.floor(between(0, 20))}.${Math.floor(between(0, 15))}`,
        Math.round(size * 100) / 100, dependencies, Math.random() < 0.12));
    }
    selected.add(name);
    result.push(catalog.get(name));
  }
  return result;
}

function tarball(packageInfo) {
  const { name, version: release } = packageInfo;
  return `https://registry.npmjs.org/${name}/-/${name}-${release}.tgz`;
}

/**
 * Simulate a tarball transfer using elapsed time and the shared network speed.
 * @param {Terminal} terminal
 * @param {Package} packageInfo
 * @param {NetworkState} network - Reused by all downloads.
 * @returns {Promise<void>}
 */
async function download(terminal, packageInfo, network) {
  const total = packageInfo.sizeMb;
  const url = tarball(packageInfo);
  const started = performance.now();
  let previous = started;
  let transferred = 0;
  while (transferred < total) {
    await sleep(FRAME_MS);
    const now = performance.now();
    const speed = network.update();
    transferred = Math.min(total, transferred + speed * (now - previous) / 1000);
    previous = now;
    // No per-package progress line: npm renders one spinner independently
    // of the transfer. Elapsed time still follows the shared network speed.
  }
  terminal.log("http", "fetch", `GET 200 ${url} ${Math.round(performance.now() - started)}ms (cache miss)`);
}

/**
 * Render one package's cache hit or download and queue occasional native builds.
 * @param {Terminal} terminal
 * @param {PackageEntry} entry
 * @param {NetworkState} network
 * @param {Package[]} builds - Output list of packages requiring a build step.
 * @returns {Promise<void>}
 */
async function collectPackage(terminal, entry, network, builds) {
  const item = entry.package;
  const cached = Math.random() < 0.2;
  if (!cached && Math.random() < 0.03) {
    terminal.log("warn", "tarball", `tarball data for ${item.name}@${tarball(item)} seems to be corrupted. Trying again.`);
    await sleep(between(300, 700));
  }
  if (cached) {
    await sleep(between(90, 250));
    terminal.log("http", "fetch", `GET 200 ${tarball(item)} 0ms (cache hit)`);
  } else {
    await download(terminal, item, network);
  }
  if (item.native && Math.random() < 0.3) builds.push(item);
}

/**
 * Display simulated native install scripts for this batch.
 * @param {Terminal} terminal
 * @param {Package[]} builds
 * @returns {Promise<void>}
 */
async function buildPackages(terminal, builds) {
  for (const item of builds) {
    terminal.log("info", "run", `${item.name}@${item.version} install node_modules/${item.name} node install.js`);
    const duration = between(600, 1400);
    await sleep(duration);
    terminal.log("info", "run", `${item.name}@${item.version} install { code: 0, signal: null }`);
  }
}

/**
 * Wait for simulated reification without printing a final success line.
 * @returns {Promise<void>}
 */
async function installBatch() {
  // Reification takes time but npm prints its summary only once it finishes.
  // A new batch follows, so neither a success line nor a fabricated log is emitted.
  await sleep(between(700, 1500));
}

/**
 * Repeatedly mix real dependency trees with stable fictional packages, sharing
 * one network state across every collection/build/install cycle.
 * @param {Options} args
 * @param {Terminal} terminal
 * @returns {Promise<never>} Runs until interrupted or an error occurs.
 */
async function runForever(args, terminal) {
  terminal.log("verbose", "cli", `node@v${args.node.text} npm@${args.npm.text}`);
  terminal.log("info", "using", `npm@${args.npm.text}`);
  terminal.log("info", "using", `node@v${args.node.text}`);
  terminal.log("verbose", "title", "npm install");
  terminal.log("verbose", "argv", `"install" "--loglevel" "${args.loglevel}"`);
  const network = new NetworkState(); // Shared across all packages and batches.
  const catalog = new Map(); // Reuse each fictional package's definition for this run.
  let roots = [];
  while (true) {
    if (roots.length === 0) roots = shuffle([...ROOT_PACKAGES]);
    const entries = dependencyOrder(roots.pop());
    const known = new Set(entries.map((entry) => entry.package.name));
    if (Math.random() < 0.4) {
      for (const entry of dependencyOrder(choose(ROOT_PACKAGES))) {
        if (!known.has(entry.package.name)) {
          entries.push(entry);
          known.add(entry.package.name);
        }
      }
    }
    for (const item of virtualPackages(Math.floor(between(1, 5)), catalog, [...known])) {
      entries.splice(Math.floor(between(0, entries.length + 1)), 0, { package: item, parent: "" });
    }
    const builds = [];
    for (const entry of entries) await collectPackage(terminal, entry, network, builds);
    await buildPackages(terminal, builds);
    await installBatch();
  }
}

/** Parse options, install signal handlers, and start the endless simulation. */
function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`npm error ${error.message}\nTry --help for usage.`);
    process.exitCode = 1;
    return;
  }
  if (args.help) {
    console.log("Usage: node install.js [--node VERSION] [--npm VERSION] [--loglevel LEVEL]\n" +
      "Log levels: notice (default), http, info, verbose.\n" +
      "Simulate an endless npm install; versions default to the installed Node.js and npm.\n" +
      "Press Ctrl+C to stop. No packages are installed.");
    return;
  }

  const terminal = new Terminal(args.loglevel);
  const stop = (signal) => {
    terminal.stop();
    terminal.log("error", "", `process terminated (${signal})`);
    process.exit(signal === "SIGINT" ? 130 : 143);
  };
  process.on("SIGINT", () => stop("SIGINT"));
  process.on("SIGTERM", () => stop("SIGTERM"));
  terminal.start();
  runForever(args, terminal).catch((error) => {
    terminal.stop();
    terminal.log("error", "", error.message);
    process.exitCode = 1;
  });
}

main();
