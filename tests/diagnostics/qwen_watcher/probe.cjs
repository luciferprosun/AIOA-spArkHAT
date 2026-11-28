#!/usr/bin/env node
'use strict';

// Standalone observation only. No AIOA evaluator or Native runtime is invoked.
// The two filter expressions reproduce the comparator under discussion in:
// https://github.com/QwenLM/qwen-code/issues/17489#issuecomment-7174526550
// The independent disk/event/evaluator split follows:
// https://github.com/luciferprosun/AIOA-spArkHAT/issues/14#issuecomment-7211138488
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { performance } = require('node:perf_hooks');

const READY_TIMEOUT_MS = 10_000;
const IO_TIMEOUT_MS = 10_000;
const CLOSE_TIMEOUT_MS = 5_000;
const MAX_TRACE_RECORDS = 50_000;
const MAX_EVENTS_PER_ARM = 10_000;
const CHILD_NAME = '.qwen';
const WATCH_OPTIONS = Object.freeze({ ignoreInitial: true, depth: 0, usePolling: false });
const AIOA_EVALUATOR = Object.freeze({
  status: 'UNIMPLEMENTED',
  reason: 'No AIOA evaluator invoked by this standalone watcher probe',
});

function errorInfo(error) {
  return { name: error.name || 'Error', code: error.code || null, message: String(error.message || error) };
}

function issue(code, message) {
  return Object.assign(new Error(message), { code });
}

function parseArgs(argv) {
  const result = { output: null, windowMs: 3000, pairs: 3, credit: 'LuciferSun' };
  const seen = new Set();
  const fields = { '--output': 'output', '--window-ms': 'windowMs', '--pairs': 'pairs', '--credit': 'credit' };
  for (let i = 0; i < argv.length; i += 2) {
    const flag = argv[i];
    if (!Object.hasOwn(fields, flag) || seen.has(flag) || argv[i + 1] === undefined) {
      throw issue('INVALID_ARGUMENT', `Unknown, duplicate, or incomplete option: ${flag}`);
    }
    seen.add(flag);
    result[fields[flag]] = argv[i + 1];
  }
  if (!result.output || !path.isAbsolute(result.output) || path.extname(result.output).toLowerCase() !== '.json') {
    throw issue('INVALID_OUTPUT', '--output must be an absolute filename ending in .json');
  }
  for (const [field, min, max] of [['windowMs', 1000, 15000], ['pairs', 1, 10]]) {
    if (!/^\d+$/.test(String(result[field]))) throw issue('INVALID_ARGUMENT', `${field} must be an integer`);
    result[field] = Number(result[field]);
    if (result[field] < min || result[field] > max) throw issue('INVALID_ARGUMENT', `${field} must be in [${min}, ${max}]`);
  }
  if (typeof result.credit !== 'string' || result.credit.length < 1 || result.credit.length > 200 || /[\r\n\0]/.test(result.credit)) {
    throw issue('INVALID_ARGUMENT', '--credit must contain 1–200 characters without line breaks or NUL');
  }
  result.output = path.normalize(result.output);
  result.trace = result.output.slice(0, -5) + '.trace.jsonl';
  return result;
}

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function writeAllText(fd, text) {
  const buffer = Buffer.from(text, 'utf8');
  let offset = 0;
  while (offset < buffer.length) {
    const written = fs.writeSync(fd, buffer, offset, buffer.length - offset);
    if (written <= 0) throw issue('SHORT_WRITE', 'Evidence write made no forward progress');
    offset += written;
  }
}

function packageInfo(packageName, searchFrom) {
  const entry = require.resolve(packageName, searchFrom ? { paths: [searchFrom] } : undefined);
  let directory = path.dirname(entry);
  for (let i = 0; i < 8; i++) {
    const filename = path.join(directory, 'package.json');
    if (fs.existsSync(filename)) {
      const metadata = JSON.parse(fs.readFileSync(filename, 'utf8'));
      if (metadata.name === packageName) return { name: packageName, version: metadata.version, entry, package_json: filename };
    }
    const parent = path.dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }
  throw issue('PACKAGE_METADATA_MISSING', `Cannot locate actual metadata for ${packageName}`);
}

function statInfo(stat) {
  const result = { is_directory: stat.isDirectory(), is_file: stat.isFile() };
  for (const field of ['dev', 'ino', 'mode', 'nlink', 'uid', 'gid', 'rdev', 'size', 'blksize', 'blocks', 'atimeNs', 'mtimeNs', 'ctimeNs', 'birthtimeNs']) {
    if (stat[field] !== undefined) result[field] = String(stat[field]);
  }
  result.mode_octal = stat.mode.toString(8);
  return result;
}

function statfsInfo(stat) {
  const result = {};
  for (const field of ['type', 'bsize', 'blocks', 'bfree', 'bavail', 'files', 'ffree']) result[field] = String(stat[field]);
  result.type_hex = `0x${stat.type.toString(16)}`;
  return result;
}

async function bounded(promise, ms, phase) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(issue('TIMEOUT', `${phase} exceeded ${ms} ms`)), ms); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

function expectedPattern(platform) {
  if (platform === 'win32') return {
    platform, raw: { root_ignored: true, matching_addDir: false },
    normalized: { root_ignored: false, matching_addDir: true },
    disk_directory_present_in_both: true,
    scope: 'Native Windows paths with consistent drive-letter case; bootstrap creation only',
  };
  if (platform === 'linux') return {
    platform, raw: { root_ignored: false, matching_addDir: true },
    normalized: { root_ignored: false, matching_addDir: true },
    disk_directory_present_in_both: true,
    scope: 'Native Linux absolute paths; bootstrap creation only',
  };
  return { platform, scope: 'No expected pattern specified for this platform' };
}

function classify(pair, expected) {
  const observation = {};
  for (const armName of ['raw', 'normalized']) {
    const arm = pair[armName];
    observation[armName] = arm ? {
      root_ignored: arm.watcher.first_root_callback?.ignored ?? null,
      matching_addDir: arm.watcher.matching_addDir_in_window > 0,
      matching_addDir_count: arm.watcher.matching_addDir_in_window,
      disk_directory_present: arm.disk.after_creation?.stat?.is_directory ?? false,
      status: arm.status,
    } : null;
  }
  if (pair.raw?.status !== 'complete' || pair.normalized?.status !== 'complete') {
    return { status: 'invalid_setup_or_capture', expected, observation };
  }
  if (!expected.raw) return { status: 'unspecified_platform', expected, observation };
  const matches = ['raw', 'normalized'].every(name =>
    observation[name].root_ignored === expected[name].root_ignored &&
    observation[name].matching_addDir === expected[name].matching_addDir &&
    observation[name].disk_directory_present === true);
  return { status: matches ? 'matches_expected_pattern' : 'unexpected_observation', expected, observation };
}

async function main() {
  let options;
  try { options = parseArgs(process.argv.slice(2)); }
  catch (error) {
    console.error(JSON.stringify({ status: 'setup_error', error: errorInfo(error), aioa_evaluator: AIOA_EVALUATOR }));
    return 1;
  }

  const monotonicStart = performance.now();
  const stamp = () => ({ wall_time: new Date().toISOString(), elapsed_ms: Number((performance.now() - monotonicStart).toFixed(3)) });
  const summary = {
    schema_version: 'qwen-watcher-probe/v1',
    status: 'setup_error',
    scope: 'Real Chokidar bootstrap creation observations; not a Qwen application lifecycle test or Native qualification',
    run_id: crypto.randomUUID(),
    credit: options.credit,
    started: stamp(),
    script: { path: __filename, sha256: sha256(fs.readFileSync(__filename)) },
    settings: {
      pairs: options.pairs, observation_window_ms: options.windowMs,
      watch_options: WATCH_OPTIONS, ready_timeout_ms: READY_TIMEOUT_MS,
      io_timeout_ms: IO_TIMEOUT_MS, close_timeout_ms: CLOSE_TIMEOUT_MS,
      max_trace_records: MAX_TRACE_RECORDS, max_events_per_arm: MAX_EVENTS_PER_ARM,
      arm_order: ['raw', 'normalized'],
      timing: 'Window starts immediately before mkdir; callbacks during mkdir and independent stat are retained',
    },
    environment: {
      platform: process.platform, arch: process.arch, node: process.version,
      node_versions: process.versions, os_release: os.release(), os_version: os.version(),
      temporary_directory: os.tmpdir(),
      polling_environment: {
        CHOKIDAR_USEPOLLING: process.env.CHOKIDAR_USEPOLLING ?? null,
        CHOKIDAR_INTERVAL: process.env.CHOKIDAR_INTERVAL ?? null,
      },
      ci_identity: {
        AIOA_TESTED_SHA: process.env.AIOA_TESTED_SHA ?? null,
        GITHUB_REPOSITORY: process.env.GITHUB_REPOSITORY ?? null,
        GITHUB_RUN_ID: process.env.GITHUB_RUN_ID ?? null,
        GITHUB_RUN_ATTEMPT: process.env.GITHUB_RUN_ATTEMPT ?? null,
      },
      windows_runner_supplemental: null,
    },
    expected_pattern: expectedPattern(process.platform),
    aioa_evaluator: AIOA_EVALUATOR,
    artifacts: { summary_json: options.output, raw_trace_jsonl: options.trace },
    pairs: [], errors: [],
  };
  let traceFd;
  let summaryFd;
  let traceRecords = 0;
  let suppressedRecords = 0;
  let traceFailure = null;
  let traceClosed = false;
  function record(kind, data = {}) {
    if (traceFailure || traceClosed) { suppressedRecords++; return traceFailure || issue('TRACE_CLOSED', 'Trace is already closed'); }
    try {
      if (traceRecords >= MAX_TRACE_RECORDS) throw issue('TRACE_RECORD_LIMIT', `Capture exceeded ${MAX_TRACE_RECORDS} records; capture is invalid`);
      const line = JSON.stringify({ sequence: ++traceRecords, ...stamp(), kind, ...data }, (_, value) => typeof value === 'bigint' ? String(value) : value) + '\n';
      writeAllText(traceFd, line);
      return null;
    } catch (error) {
      traceFailure = error;
      suppressedRecords++;
      try {
        writeAllText(traceFd, JSON.stringify({ sequence: ++traceRecords, ...stamp(), kind: 'capture_error', error: errorInfo(error), capture_incomplete: true }) + '\n');
      } catch { /* The summary also reports trace write failures. */ }
      return error;
    }
  }
  function mustRecord(kind, data) { const error = record(kind, data); if (error) throw error; }

  try {
    fs.mkdirSync(path.dirname(options.output), { recursive: true });
    // Exclusive creation prevents a later run from silently replacing evidence.
    summaryFd = fs.openSync(options.output, 'wx');
    traceFd = fs.openSync(options.trace, 'wx');
    mustRecord('run_start', { run_id: summary.run_id, script: summary.script, settings: summary.settings, aioa_evaluator: AIOA_EVALUATOR });
    const polling = process.env.CHOKIDAR_USEPOLLING;
    if (polling !== undefined && !['false', '0'].includes(polling.toLowerCase())) {
      throw issue('POLLING_ENVIRONMENT_OVERRIDE', 'CHOKIDAR_USEPOLLING must be absent, false, or 0 for this native watching probe');
    }
    if (process.env.CHOKIDAR_INTERVAL !== undefined) {
      throw issue('POLLING_ENVIRONMENT_OVERRIDE', 'CHOKIDAR_INTERVAL must be absent for this controlled probe');
    }
    const supplemental = process.env.QWEN_WATCHER_WINDOWS_INFO;
    if (supplemental !== undefined) {
      if (Buffer.byteLength(supplemental) > 16_384) throw issue('SUPPLEMENTAL_INFO_LIMIT', 'QWEN_WATCHER_WINDOWS_INFO exceeds 16 KiB');
      const info = JSON.parse(supplemental);
      if (!info || typeof info !== 'object' || Array.isArray(info)) throw issue('SUPPLEMENTAL_INFO_INVALID', 'QWEN_WATCHER_WINDOWS_INFO must be a JSON object');
      summary.environment.windows_runner_supplemental = { provenance: 'runner_supplied', value: info };
    }
    const chokidarPackage = packageInfo('chokidar');
    summary.environment.chokidar = chokidarPackage;
    summary.environment.readdirp = packageInfo('readdirp', path.dirname(chokidarPackage.entry));
    if (chokidarPackage.version !== '4.0.3') throw issue('DEPENDENCY_VERSION_MISMATCH', `Expected Chokidar 4.0.3, observed ${chokidarPackage.version}`);
    const chokidar = require('chokidar');
    mustRecord('environment', { environment: summary.environment });

    async function runArm(pairNumber, armName) {
      const arm = {
        pair: pairNumber, comparator: armName, status: 'setup_error', started: stamp(),
        parent: null, child: null, disk: {}, filesystem: {}, window: null,
        watcher: { first_callback: null, first_root_callback: null, ready: null, effective_options: null,
          events: [], errors: [], raw_event_count: 0, predicate_callback_count: 0, matching_addDir_in_window: 0 },
        capture: { complete: true, suppressed_events: 0 },
        cleanup: { watcher_closed: false, temporary_parent_removed: false }, errors: [],
      };
      let watcher;
      let windowTimer;
      let readyTimer;
      let firstFailure;
      let signalFailure;
      let windowOpen = false;
      let armFinalized = false;
      const failure = new Promise(resolve => { signalFailure = resolve; });
      const fail = error => {
        if (!firstFailure) { firstFailure = error; signalFailure(error); }
      };
      const emit = (kind, data = {}) => {
        if (armFinalized) return;
        const error = record(kind, { pair: pairNumber, arm: armName, ...data });
        if (error) fail(error);
      };
      async function guarded(promise) {
        const result = await Promise.race([
          Promise.resolve(promise).then(value => ({ value }), error => ({ error })),
          failure.then(error => ({ error })),
        ]);
        if (result.error) throw result.error;
        return result.value;
      }
      const io = (promise, phase) => guarded(bounded(promise, IO_TIMEOUT_MS, phase));
      try {
        arm.parent = await io(fsp.mkdtemp(path.join(os.tmpdir(), `qwen-watcher-${pairNumber}-${armName}-`)), 'create fresh parent');
        if (!path.isAbsolute(arm.parent) || path.basename(arm.parent) === CHILD_NAME) throw issue('INVALID_PARENT', 'Temporary parent must be absolute and have a different basename from the child');
        arm.child = path.join(arm.parent, CHILD_NAME);
        emit('arm_start', { parent: arm.parent, child: arm.child, watch_options: WATCH_OPTIONS });
        arm.filesystem.parent_stat = statInfo(await io(fsp.stat(arm.parent, { bigint: true }), 'stat parent'));
        if (!arm.filesystem.parent_stat.is_directory) throw issue('INVALID_PARENT', 'Parent is not a directory');
        arm.filesystem.parent_statfs = statfsInfo(await io(fsp.statfs(arm.parent, { bigint: true }), 'statfs parent'));
        emit('filesystem', { filesystem: arm.filesystem });
        // This stat is independent of the watcher and is made before constructing it.
        try {
          const existing = await io(fsp.stat(arm.child, { bigint: true }), 'verify exact child absence');
          arm.disk.before_creation = { ...stamp(), path: arm.child, observer: 'independent_fs_stat', exists: true, stat: statInfo(existing) };
          emit('disk_before_creation', arm.disk.before_creation);
          throw issue('CHILD_ALREADY_EXISTS', 'Exact .qwen child unexpectedly exists before watching');
        } catch (error) {
          if (error.code !== 'ENOENT') throw error;
          arm.disk.before_creation = { ...stamp(), path: arm.child, observer: 'independent_fs_stat', exists: false, error: errorInfo(error) };
          emit('disk_before_creation', arm.disk.before_creation);
        }
        const resolvedParent = path.resolve(arm.parent);
        const ignored = entryPath => {
          const ignoredDecision = armName === 'raw'
            ? entryPath !== arm.parent && path.basename(entryPath) !== CHILD_NAME
            : path.resolve(entryPath) !== resolvedParent && path.basename(entryPath) !== CHILD_NAME;
          const callback = { ...stamp(), raw_path: entryPath, ignored: ignoredDecision,
            root_identified_by_path_resolve: path.resolve(entryPath) === resolvedParent };
          arm.watcher.predicate_callback_count++;
          if (!arm.watcher.first_callback) arm.watcher.first_callback = callback;
          if (callback.root_identified_by_path_resolve && !arm.watcher.first_root_callback) arm.watcher.first_root_callback = callback;
          emit('ignored_callback', callback);
          return ignoredDecision;
        };
        // Construct an empty watcher so listeners exist before add() can emit.
        watcher = new chokidar.FSWatcher({ ...WATCH_OPTIONS, ignored });
        arm.watcher.effective_options = {
          ignoreInitial: watcher.options.ignoreInitial,
          depth: watcher.options.depth,
          usePolling: watcher.options.usePolling,
          persistent: watcher.options.persistent,
          atomic: watcher.options.atomic,
          awaitWriteFinish: watcher.options.awaitWriteFinish,
          interval: watcher.options.interval,
          binaryInterval: watcher.options.binaryInterval,
          followSymlinks: watcher.options.followSymlinks,
        };
        if (watcher.options.usePolling !== false || watcher.options.ignoreInitial !== true || watcher.options.depth !== 0) {
          throw issue('WATCH_OPTIONS_MISMATCH', 'Effective Chokidar options differ from the controlled options');
        }
        emit('watcher_options', { effective_options: arm.watcher.effective_options });
        watcher.on('all', (event, eventPath, stat) => {
          if (armFinalized) return;
          if (arm.watcher.events.length >= MAX_EVENTS_PER_ARM) {
            arm.capture.complete = false;
            arm.capture.suppressed_events++;
            emit('capture_error', { code: 'EVENT_LIMIT', limit: MAX_EVENTS_PER_ARM, capture_incomplete: true });
            fail(issue('EVENT_LIMIT', `More than ${MAX_EVENTS_PER_ARM} events in one arm; capture is invalid`));
            return;
          }
          const item = { ...stamp(), event, raw_path: eventPath, in_observation_window: windowOpen,
            matches_exact_child_by_path_resolve: path.resolve(eventPath) === path.resolve(arm.child),
            watcher_supplied_stat: stat ? statInfo(stat) : null };
          arm.watcher.events.push(item);
          if (item.in_observation_window && event === 'addDir' && item.matches_exact_child_by_path_resolve) arm.watcher.matching_addDir_in_window++;
          emit('watcher_event', item);
        });
        watcher.on('raw', (event, eventPath, details) => {
          if (armFinalized) return;
          arm.watcher.raw_event_count++;
          emit('watcher_raw_event', { event, raw_path: eventPath, details, in_observation_window: windowOpen });
        });
        watcher.on('error', error => {
          if (armFinalized) return;
          const observed = { ...stamp(), ...errorInfo(error), in_observation_window: windowOpen };
          arm.watcher.errors.push(observed);
          emit('watcher_error', observed);
          // Preserve the full fixed window for runtime errors; a missing ready
          // event is handled separately by the setup deadline below.
        });
        const ready = new Promise(resolve => watcher.once('ready', () => {
          arm.watcher.ready = stamp();
          emit('watcher_ready', { ready: arm.watcher.ready, meaning: 'Ready does not establish root admission or delivery' });
          resolve();
        }));
        const readyDeadline = new Promise((_, reject) => { readyTimer = setTimeout(() => reject(issue('READY_TIMEOUT', `No ready event within ${READY_TIMEOUT_MS} ms`)), READY_TIMEOUT_MS); });
        watcher.add(arm.parent);
        await guarded(Promise.race([ready, readyDeadline]));
        clearTimeout(readyTimer);
        if (!arm.watcher.first_root_callback) throw issue('MISSING_ROOT_CALLBACK', 'No root predicate callback was captured');

        // Start timing BEFORE mkdir. Do not derive the disk observation from
        // Chokidar stats or stop early after a matching addDir event.
        const windowStart = performance.now();
        windowOpen = true;
        arm.window = { requested_ms: options.windowMs, started: stamp(), completed: false };
        emit('observation_window_start', { window: arm.window });
        const windowDone = new Promise(resolve => {
          windowTimer = setTimeout(() => {
            windowOpen = false;
            arm.window.ended = stamp();
            arm.window.actual_elapsed_ms = Number((performance.now() - windowStart).toFixed(3));
            arm.window.completed = true;
            emit('observation_window_end', { window: arm.window });
            resolve();
          }, options.windowMs);
        });
        arm.disk.mkdir = { started: stamp(), path: arm.child, successful: false };
        emit('mkdir_start', arm.disk.mkdir);
        await io(fsp.mkdir(arm.child), 'mkdir exact child');
        arm.disk.mkdir.successful = true;
        arm.disk.mkdir.completed = stamp();
        emit('mkdir_complete', arm.disk.mkdir);
        const independentStat = await io(fsp.stat(arm.child, { bigint: true }), 'independent stat exact child after mkdir');
        arm.disk.after_creation = { ...stamp(), path: arm.child, observer: 'independent_fs_stat', exists: true, stat: statInfo(independentStat) };
        emit('disk_after_creation', arm.disk.after_creation);
        if (!independentStat.isDirectory()) throw issue('CHILD_NOT_DIRECTORY', 'Independent fs.stat did not observe a directory at the exact child path');
        arm.filesystem.child_statfs = statfsInfo(await io(fsp.statfs(arm.child, { bigint: true }), 'statfs exact child'));
        emit('child_statfs', { path: arm.child, statfs: arm.filesystem.child_statfs });
        await guarded(windowDone);
        if (firstFailure) throw firstFailure;
        if (arm.watcher.errors.length) throw issue('WATCHER_ERROR', `Observed ${arm.watcher.errors.length} watcher error(s); the complete window was retained`);
        arm.status = 'complete';
      } catch (error) {
        arm.errors.push({ ...stamp(), ...errorInfo(error) });
        emit('arm_setup_or_capture_error', { error: errorInfo(error) });
      } finally {
        clearTimeout(readyTimer);
        clearTimeout(windowTimer);
        windowOpen = false;
        if (arm.window && !arm.window.completed) arm.window.aborted = stamp();
        if (watcher) {
          try {
            await bounded(watcher.close(), CLOSE_TIMEOUT_MS, 'watcher close');
            arm.cleanup.watcher_closed = true;
            emit('watcher_closed');
          } catch (error) { arm.errors.push({ ...stamp(), phase: 'close', ...errorInfo(error) }); }
        } else arm.cleanup.watcher_closed = true;
        // Remove the fresh directory only after the watcher has closed.
        if (arm.parent && arm.cleanup.watcher_closed) {
          try {
            await bounded(fsp.rm(arm.parent, { recursive: true, force: true, maxRetries: 2, retryDelay: 100 }), IO_TIMEOUT_MS, 'remove fresh parent');
            arm.cleanup.temporary_parent_removed = true;
            emit('temporary_parent_removed', { parent: arm.parent });
          } catch (error) { arm.errors.push({ ...stamp(), phase: 'cleanup', ...errorInfo(error) }); }
        }
        if (firstFailure && !arm.errors.some(error => error.code === firstFailure.code && error.message === firstFailure.message)) {
          arm.errors.push({ ...stamp(), phase: 'capture', ...errorInfo(firstFailure) });
        }
        if (arm.watcher.errors.length && !arm.errors.some(error => error.code === 'WATCHER_ERROR')) {
          arm.errors.push({ ...stamp(), code: 'WATCHER_ERROR', message: `Observed ${arm.watcher.errors.length} watcher error(s)` });
        }
        if (arm.errors.length || firstFailure) arm.status = 'setup_error';
        if (firstFailure || traceFailure) arm.capture.complete = false;
        arm.finished = stamp();
        emit('arm_end', { status: arm.status, cleanup: arm.cleanup, event_count: arm.watcher.events.length,
          matching_addDir_in_window: arm.watcher.matching_addDir_in_window, errors: arm.errors });
        armFinalized = true;
      }
      return arm;
    }

    for (let number = 1; number <= options.pairs; number++) {
      const pair = { pair: number };
      summary.pairs.push(pair);
      pair.raw = await runArm(number, 'raw');
      if (!traceFailure) pair.normalized = await runArm(number, 'normalized');
      pair.classification = classify(pair, summary.expected_pattern);
      mustRecord('pair_classification', { pair: number, classification: pair.classification });
      if (pair.raw.status !== 'complete' || pair.normalized?.status !== 'complete') break;
    }
    summary.status = summary.pairs.length === options.pairs && summary.pairs.every(pair =>
      pair.raw.status === 'complete' && pair.normalized?.status === 'complete') ? 'complete' : 'setup_error';
  } catch (error) {
    summary.errors.push({ ...stamp(), ...errorInfo(error) });
    record('setup_error', { error: errorInfo(error) });
  } finally {
    if (traceFailure) {
      summary.status = 'setup_error';
      summary.errors.push({ phase: 'trace_capture', ...errorInfo(traceFailure) });
    }
    summary.finished = stamp();
    summary.counts = {
      requested_pairs: options.pairs,
      completed_pairs: summary.pairs.filter(pair => pair.raw?.status === 'complete' && pair.normalized?.status === 'complete').length,
      expected_pattern_matches: summary.pairs.filter(pair => pair.classification?.status === 'matches_expected_pattern').length,
      unexpected_observations: summary.pairs.filter(pair => pair.classification?.status === 'unexpected_observation').length,
      watcher_events: summary.pairs.reduce((sum, pair) => sum + (pair.raw?.watcher.events.length || 0) + (pair.normalized?.watcher.events.length || 0), 0),
      watcher_errors: summary.pairs.reduce((sum, pair) => sum + (pair.raw?.watcher.errors.length || 0) + (pair.normalized?.watcher.errors.length || 0), 0),
    };
    if (traceFd !== undefined) {
      record('run_end', { status: summary.status, counts: summary.counts, errors: summary.errors, aioa_evaluator: AIOA_EVALUATOR });
      if (traceFailure) {
        summary.status = 'setup_error';
        if (!summary.errors.some(error => error.phase === 'trace_capture')) summary.errors.push({ phase: 'trace_capture', ...errorInfo(traceFailure) });
      }
      try { fs.fsyncSync(traceFd); fs.closeSync(traceFd); }
      catch (error) { summary.status = 'setup_error'; summary.errors.push({ phase: 'trace_finalize', ...errorInfo(error) }); }
      traceClosed = true;
      try {
        const trace = fs.readFileSync(options.trace);
        summary.artifacts.raw_trace_sha256 = sha256(trace);
        summary.artifacts.raw_trace_bytes = trace.length;
      } catch (error) { summary.status = 'setup_error'; summary.errors.push({ phase: 'trace_read', ...errorInfo(error) }); }
    }
    summary.artifacts.trace_records = traceRecords;
    summary.artifacts.suppressed_records = suppressedRecords;
    summary.artifacts.capture_complete = traceFd !== undefined && !traceFailure && suppressedRecords === 0 &&
      summary.pairs.every(pair => pair.raw?.capture.complete !== false && pair.normalized?.capture.complete !== false);
    if (summaryFd !== undefined) {
      try { writeAllText(summaryFd, JSON.stringify(summary, null, 2) + '\n'); fs.fsyncSync(summaryFd); fs.closeSync(summaryFd); }
      catch (error) { summary.status = 'setup_error'; console.error(JSON.stringify({ status: 'setup_error', phase: 'summary_write', error: errorInfo(error) })); }
    }
  }
  console.log(JSON.stringify({ status: summary.status, counts: summary.counts, output: options.output,
    trace: options.trace, script_sha256: summary.script.sha256, aioa_evaluator: AIOA_EVALUATOR }));
  return summary.status === 'complete' ? 0 : 1;
}

main().then(code => {
  process.exitCode = code;
  // A failed close must not leave the diagnostics process hanging forever.
  // Synchronous evidence writes above finish before this fallback can fire.
  if (code !== 0) setTimeout(() => process.exit(code), 250).unref();
}).catch(error => {
  console.error(JSON.stringify({ status: 'setup_error', error: errorInfo(error), aioa_evaluator: AIOA_EVALUATOR }));
  process.exitCode = 1;
  setTimeout(() => process.exit(1), 250).unref();
});
