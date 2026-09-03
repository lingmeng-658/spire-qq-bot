#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');

const SAMPLE_SPECS = Object.freeze([
  { game: 'sts1', id: 'STRIKE_R', purpose: 'short Chinese description' },
  { game: 'sts1', id: 'REBOUND', purpose: 'long Chinese description' },
  { game: 'sts2', id: 'ABRASIVE', purpose: 'ordinary STS2 card' },
  { game: 'sts2', id: 'ALIGNMENT', purpose: 'three-star cost' },
]);

const TYPE_ZH = Object.freeze({
  Attack: '攻击',
  Skill: '技能',
  Power: '能力',
  Curse: '诅咒',
  Status: '状态',
  Quest: '任务',
});

const STS1_PORTRAIT_OVERRIDES = Object.freeze({
  CURSEOFTHEBELL: 'curse_of_the_bell.png',
});

const SKIP_REASONS = Object.freeze({
  'sts1:IMPULSE': 'missing portrait, empty description, and no Simplified Chinese localization',
});

function selectorForGame(game) {
  if (game === 'sts1') return '.cr1';
  if (game === 'sts2') return '.cr';
  throw new Error(`unsupported game: ${game}`);
}

function portraitFilename(game, id) {
  if (game === 'sts1' && STS1_PORTRAIT_OVERRIDES[id]) {
    return STS1_PORTRAIT_OVERRIDES[id];
  }
  return `${id.toLowerCase()}.png`;
}

function skipReason(game, id) {
  return SKIP_REASONS[`${game}:${id}`] ?? null;
}

function loadCards(projectRoot, game) {
  const rawPath = path.join(projectRoot, 'data', 'raw', `${game}_cards.json`);
  return JSON.parse(fs.readFileSync(rawPath, 'utf8'));
}

function buildExportPlan(projectRoot, outputRoot, options = {}) {
  const upgraded = Boolean(options && options.upgraded);
  const cardsByGame = new Map();
  for (const game of ['sts1', 'sts2']) {
    cardsByGame.set(game, new Map(loadCards(projectRoot, game).map((card) => [card.id, card])));
  }

  return SAMPLE_SPECS.map((spec) => {
    const card = cardsByGame.get(spec.game).get(spec.id);
    if (!card) throw new Error(`sample card missing from data/raw: ${spec.game}:${spec.id}`);
    const item = {
      ...card,
      ...spec,
      selector: selectorForGame(spec.game),
      portraitFile: portraitFilename(spec.game, spec.id),
      typeZh: TYPE_ZH[card.type] ?? card.type,
      upgraded,
      outputPath: path.join(outputRoot, spec.game, upgraded ? 'upgraded' : '', `${spec.id}.png`),
    };
    if (upgraded && !cardHasUpgrade(card)) {
      item.status = 'skipped';
      item.reason = 'no_upgrade';
      item.detail = `Card has no upgrade data: ${spec.id}`;
    } else {
      item.status = 'pending';
    }
    return item;
  });
}

function cardHasUpgrade(card) {
  return Boolean(card && card.upgrade && Object.keys(card.upgrade).length > 0);
}

function compactText(value) {
  return String(value ?? '').replace(/\s+/g, '');
}

function validateCaptureState(sample, state) {
  if (!state.fontsReady) throw new Error(`${sample.game}:${sample.id} fonts are not ready`);
  if (!state.imagesLoaded) throw new Error(`${sample.game}:${sample.id} has an unloaded card image`);
  if (!state.descriptionFits) throw new Error(`${sample.game}:${sample.id} description is clipped`);
  if (!state.isolated) throw new Error(`${sample.game}:${sample.id} card element is not isolated from page chrome`);

  if (!sample.upgraded && sample.game === 'sts1' && sample.id === 'REBOUND') {
    const expected = compactText(sample.description);
    const actual = compactText(state.descriptionText);
    if (!expected || !actual.includes(expected)) {
      throw new Error(`${sample.game}:${sample.id} description text is incomplete`);
    }
  }

  if (sample.game === 'sts2' && sample.id === 'ALIGNMENT' && state.starCost !== '3') {
    throw new Error(`${sample.game}:${sample.id} expected star cost 3, got ${state.starCost ?? 'missing'}`);
  }
}

function readPngDimensions(buffer) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (buffer.length < 24 || !buffer.subarray(0, 8).equals(signature)) {
    throw new Error('invalid PNG header');
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith('--')) throw new Error(`unexpected argument: ${arg}`);
    const key = arg.slice(2);
    if (key === 'all' || key === 'upgraded') {
      options[key] = true;
      continue;
    }
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) throw new Error(`missing value for --${key}`);
    options[key] = value;
    index += 1;
  }
  return options;
}

function loadPlaywright(spireRoot) {
  if (spireRoot) {
    const packageRequire = createRequire(path.join(path.resolve(spireRoot), 'package.json'));
    return packageRequire('playwright');
  }
  return require('playwright');
}

function defaultBrowserExecutable(explicitPath) {
  if (explicitPath) return explicitPath;
  const candidates = process.platform === 'win32'
    ? [
        'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
      ]
    : ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'];
  return candidates.find((candidate) => fs.existsSync(candidate));
}

function browserLaunchOptions(options = {}) {
  const executablePath = defaultBrowserExecutable(options['browser-executable']);
  return { headless: true, ...(executablePath ? { executablePath } : {}) };
}

async function launchBrowser(chromium, options) {
  return chromium.launch(browserLaunchOptions(options));
}

async function waitForFontsAndCardImages(page, selector) {
  await page.evaluate(async ({ selector: cardSelector }) => {
    await document.fonts.ready;
    const images = [...document.querySelectorAll(`${cardSelector} img`)];
    await Promise.all(images.map((image) => {
      if (image.complete) {
        if (image.naturalWidth > 0) return undefined;
        throw new Error(`card image failed to load: ${image.currentSrc || image.src}`);
      }
      return new Promise((resolve, reject) => {
        const timeout = window.setTimeout(
          () => reject(new Error(`timed out loading card image: ${image.src}`)),
          15000,
        );
        image.addEventListener('load', () => {
          window.clearTimeout(timeout);
          resolve();
        }, { once: true });
        image.addEventListener('error', () => {
          window.clearTimeout(timeout);
          reject(new Error(`card image failed to load: ${image.src}`));
        }, { once: true });
      });
    }));
  }, { selector });
}

async function clickUpgradeToggle(page, selector) {
  return page.evaluate(({ cardSelector }) => {
    const card = document.querySelector(cardSelector);
    if (!card) throw new Error(`renderer element not found: ${cardSelector}`);
    const container = card.parentElement;
    if (!container) throw new Error('upgrade toggle container not found');
    const buttons = Array.from(container.querySelectorAll('button'));
    if (buttons.length < 2) throw new Error('upgrade toggle button not found');
    const upgradeButton = buttons[buttons.length - 1];
    upgradeButton.click();
    return true;
  }, { cardSelector: selector });
}

async function waitForUpgradedState(page, selector, game, timeoutMs = 15000) {
  await page.waitForFunction(
    ({ cardSelector, cardGame }) => {
      const card = document.querySelector(cardSelector);
      if (!card) return false;
      if (cardGame === 'sts1') {
        const title = card.querySelector('.cr1-title');
        return Boolean(title && title.classList.contains('cr1-title-upgraded'));
      }
      const title = card.querySelector('.cr-title');
      return Boolean(
        title
        && title.classList.contains('cr-green')
        && String(title.textContent || '').trim().endsWith('+')
      );
    },
    { cardSelector: selector, cardGame: game },
    { timeout: timeoutMs },
  );
}

async function patchSts1Renderer(page, sample) {
  await page.evaluate(({ portraitFile, typeZh }) => {
    const card = document.querySelector('.cr1');
    if (!card) throw new Error('STS1 renderer element .cr1 was not found');

    let style = document.getElementById('card-export-sts1-fixes');
    if (!style) {
      style = document.createElement('style');
      style.id = 'card-export-sts1-fixes';
      style.textContent = `
        .cr1,
        .cr1-title,
        .cr1-type,
        .cr1-desc,
        .cr1-desc-inner {
          font-family: 'SourceHanSerifSC', serif !important;
        }
        .cr1-desc-inner {
          box-sizing: border-box;
          max-width: 100%;
          width: 100%;
        }
      `;
      document.head.appendChild(style);
    }

    const type = card.querySelector('.cr1-type');
    if (type) type.textContent = typeZh;

    const portrait = card.querySelector('.cr1-portrait');
    if (portrait) {
      const desired = new URL(`/images/sts1/cards/${portraitFile}`, window.location.origin).href;
      if (portrait.src !== desired) portrait.src = desired;
    }
  }, { portraitFile: sample.portraitFile, typeZh: sample.typeZh });

  await waitForFontsAndCardImages(page, '.cr1');

  await page.evaluate(() => {
    const container = document.querySelector('.cr1-desc');
    const inner = document.querySelector('.cr1-desc-inner');
    if (!container || !inner) throw new Error('STS1 description elements were not found');

    const maximum = Math.max(8, Math.floor(Number.parseFloat(getComputedStyle(inner).fontSize)));
    let low = 8;
    let high = maximum;
    let best = 8;
    while (low <= high) {
      const size = Math.floor((low + high) / 2);
      inner.style.fontSize = `${size}px`;
      const fits = inner.scrollHeight <= container.clientHeight + 1
        && inner.scrollWidth <= container.clientWidth + 1;
      if (fits) {
        best = size;
        low = size + 1;
      } else {
        high = size - 1;
      }
    }
    inner.style.fontSize = `${best}px`;
  });
}

async function captureState(page, sample) {
  return page.evaluate(({ selector, game }) => {
    const card = document.querySelector(selector);
    if (!card) throw new Error(`renderer element not found: ${selector}`);
    const descriptionContainer = card.querySelector(game === 'sts1' ? '.cr1-desc' : '.cr-desc');
    const descriptionInner = card.querySelector(game === 'sts1' ? '.cr1-desc-inner' : '.cr-desc-inner');
    const images = [...card.querySelectorAll('img')];
    return {
      descriptionText: descriptionInner?.textContent ?? '',
      descriptionFits: Boolean(descriptionContainer && descriptionInner)
        && descriptionInner.scrollHeight <= descriptionContainer.clientHeight + 1
        && descriptionInner.scrollWidth <= descriptionContainer.clientWidth + 1,
      fontsReady: document.fonts.status === 'loaded',
      imagesLoaded: images.length > 0 && images.every((image) => image.complete && image.naturalWidth > 0),
      isolated: card.parentElement === document.body
        && document.body.children.length === 1
        && card.dataset.cardExportIsolated === 'true',
      starCost: card.querySelector('.cr-star-num')?.textContent?.trim() ?? null,
      typeText: card.querySelector(game === 'sts1' ? '.cr1-type' : '.cr-type')?.textContent?.trim() ?? null,
    };
  }, { selector: sample.selector, game: sample.game });
}

async function isolateCardElement(page, sample) {
  await page.evaluate(({ selector }) => {
    const card = document.querySelector(selector);
    if (!card) throw new Error(`renderer element not found: ${selector}`);
    document.body.replaceChildren(card);
    document.documentElement.style.background = 'transparent';
    document.body.style.margin = '0';
    document.body.style.padding = '0';
    document.body.style.width = 'max-content';
    document.body.style.height = 'max-content';
    document.body.style.overflow = 'hidden';
    document.body.style.background = 'transparent';
    card.style.setProperty('margin', '0', 'important');
    card.dataset.cardExportIsolated = 'true';
  }, { selector: sample.selector });
}

async function exportSamples(options) {
  const projectRoot = path.resolve(options['project-root'] ?? path.join(__dirname, '..'));
  const outputRoot = path.resolve(options['output-root'] ?? path.join(projectRoot, 'data', 'images'));
  const baseUrl = String(options['base-url'] ?? 'http://127.0.0.1:4324').replace(/\/$/, '');
  const spireRoot = options['spire-root'] ? path.resolve(options['spire-root']) : null;
  const plan = buildExportPlan(projectRoot, outputRoot, { upgraded: options.upgraded });
  const { chromium } = loadPlaywright(spireRoot);
  const browser = await launchBrowser(chromium, options);
  const context = await browser.newContext({
    deviceScaleFactor: 2,
    viewport: { width: 1440, height: 1200 },
  });
  const results = [];

  try {
    for (const sample of plan) {
      if (sample.status === 'skipped') {
        results.push({
          game: sample.game,
          id: sample.id,
          path: null,
          status: 'skipped',
          reason: sample.reason,
        });
        continue;
      }

      const page = await context.newPage();
      page.setDefaultTimeout(30000);
      try {
        const url = `${baseUrl}/zh/${sample.game}/cards/${encodeURIComponent(sample.id)}`;
        await page.goto(url, { waitUntil: 'networkidle' });
        const card = page.locator(sample.selector);
        await card.waitFor({ state: 'visible' });

        await page.evaluate(() => document.fonts.ready);
        if (sample.upgraded) {
          await clickUpgradeToggle(page, sample.selector);
          await waitForUpgradedState(page, sample.selector, sample.game);
        }
        if (sample.game === 'sts1') await patchSts1Renderer(page, sample);
        await waitForFontsAndCardImages(page, sample.selector);
        await isolateCardElement(page, sample);

        const state = await captureState(page, sample);
        validateCaptureState({ ...sample, upgraded: sample.upgraded }, state);

        fs.mkdirSync(path.dirname(sample.outputPath), { recursive: true });
        await card.screenshot({
          path: sample.outputPath,
          animations: 'disabled',
          omitBackground: true,
        });
        const png = fs.readFileSync(sample.outputPath);
        results.push({
          game: sample.game,
          id: sample.id,
          path: sample.outputPath,
          ...readPngDimensions(png),
          bytes: png.length,
          state,
        });
      } finally {
        await page.close();
      }
    }
  } finally {
    await context.close();
    await browser.close();
  }

  return results;
}

async function checkRendererAvailability(baseUrl) {
  const targetUrl = String(baseUrl || 'http://127.0.0.1:4324').replace(/\/$/, '');
  const { request } = require('node:http');
  const { request: requestHttps } = require('node:https');

  return new Promise((resolve, reject) => {
    const doRequest = targetUrl.startsWith('https:') ? requestHttps : request;
    const req = doRequest(targetUrl, { method: 'HEAD', timeout: 5000 }, (response) => {
      response.resume();
      if (response.statusCode >= 200 && response.statusCode < 500) {
        resolve(targetUrl);
      } else {
        reject(new Error(`Renderer is unavailable at ${targetUrl}. Start the verified local renderer before using --all.`));
      }
    });

    req.on('error', () => {
      reject(new Error(`Renderer is unavailable at ${targetUrl}. Start the verified local renderer before using --all.`));
    });
    req.on('timeout', () => {
      req.destroy(new Error(`Renderer is unavailable at ${targetUrl}. Start the verified local renderer before using --all.`));
    });
    req.end();
  });
}

async function exportAllCards(options = {}) {
  const projectRoot = path.resolve(options['project-root'] ?? path.join(__dirname, '..'));
  const outputRoot = path.resolve(options['output-root'] ?? path.join(projectRoot, 'data', 'images'));
  const baseUrl = String(options['base-url'] ?? 'http://127.0.0.1:4324').replace(/\/$/, '');
  const spireRoot = options['spire-root'] ? path.resolve(options['spire-root']) : null;
  const upgraded = Boolean(options.upgraded);

  await checkRendererAvailability(baseUrl);

  const { chromium } = loadPlaywright(spireRoot);
  const browser = await launchBrowser(chromium, options);
  const context = await browser.newContext({
    deviceScaleFactor: 2,
    viewport: { width: 1440, height: 1200 },
  });

  const results = { sts1: { total: 0, exported: 0, skipped: 0, failed: 0, failedIds: [], failedReasons: {} }, sts2: { total: 0, exported: 0, skipped: 0, failed: 0, failedIds: [], failedReasons: {} } };
  const overallFailed = [];

  try {
    for (const game of ['sts1', 'sts2']) {
      const cards = JSON.parse(fs.readFileSync(path.join(projectRoot, 'data', 'raw', `${game}_cards.json`), 'utf8'));
      const existing = new Set();
      const targetDir = path.join(outputRoot, game);
      if (fs.existsSync(targetDir)) {
        const collect = (dir) => {
          for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) {
              collect(full);
            } else {
              existing.add(path.relative(projectRoot, full).replace(/\\/g, '/'));
            }
          }
        };
        collect(targetDir);
      }

      const plan = collectCardsForExport(game, cards, existing, { upgraded });
      results[game].total = plan.length;

      for (const item of plan) {
        if (item.status === 'skipped') {
          results[game].skipped += 1;
          continue;
        }

        const page = await context.newPage();
        page.setDefaultTimeout(30000);
        try {
          const url = `${baseUrl}/zh/${game}/cards/${encodeURIComponent(item.cardId)}`;
          await page.goto(url, { waitUntil: 'networkidle' });
          const card = page.locator(item.selector);
          await card.waitFor({ state: 'visible' });
          await page.evaluate(() => document.fonts.ready);
          if (item.upgraded) {
            await clickUpgradeToggle(page, item.selector);
            await waitForUpgradedState(page, item.selector, game);
          }
          if (game === 'sts1') {
            await patchSts1Renderer(page, {
              game,
              id: item.cardId,
              selector: item.selector,
              portraitFile: portraitFilename(game, item.cardId),
              typeZh: TYPE_ZH[item.card.type] ?? item.card.type,
            });
          }
          await waitForFontsAndCardImages(page, item.selector);
          await isolateCardElement(page, { selector: item.selector });
          const state = await captureState(page, { selector: item.selector, game });
          validateCaptureState(
            { game, id: item.cardId, description: item.card.description, upgraded: item.upgraded },
            state,
          );
          fs.mkdirSync(path.dirname(path.join(projectRoot, item.outputPath)), { recursive: true });
          await card.screenshot({
            path: path.join(projectRoot, item.outputPath),
            animations: 'disabled',
            omitBackground: true,
          });
          results[game].exported += 1;
        } catch (error) {
          const reason = error && error.message ? error.message : String(error || 'unknown_error');
          results[game].failed += 1;
          results[game].failedIds.push(item.cardId);
          results[game].failedReasons[item.cardId] = reason;
          overallFailed.push({ game, cardId: item.cardId, reason });
        } finally {
          await page.close();
        }
      }
    }
  } finally {
    await context.close();
    await browser.close();
  }

  return {
    byGame: results,
    failedIds: overallFailed.map((entry) => `${entry.game}:${entry.cardId}`),
    failedReasons: overallFailed.reduce((acc, entry) => {
      acc[`${entry.game}:${entry.cardId}`] = entry.reason;
      return acc;
    }, {}),
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.all) {
    try {
      const result = await exportAllCards(options);
      process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
      return;
    } catch (error) {
      process.stderr.write(`${error.stack ?? error}\n`);
      process.exitCode = 1;
      return;
    }
  }

  const reason = skipReason('sts1', 'IMPULSE');
  process.stdout.write(`SKIP sts1:IMPULSE: ${reason}\n`);
  const results = await exportSamples(options);
  process.stdout.write(`${JSON.stringify(results, null, 2)}\n`);
}

function collectCardsForExport(game, cards, existingFiles = new Set(), options = {}) {
  const normalizedGame = String(game || '').trim().toLowerCase();
  const upgraded = Boolean(options && options.upgraded);
  const safeExisting = new Set(Array.from(existingFiles || []).map((value) => String(value).replace(/\\/g, '/')));
  const plan = [];

  for (const card of Array.isArray(cards) ? cards : []) {
    if (!card || !card.id || card.color === 'status') {
      continue;
    }

    const cardId = String(card.id).trim();
    const outputPath = path.join('data', 'images', normalizedGame, upgraded ? 'upgraded' : '', `${cardId}.png`);
    const normalizedOutputPath = outputPath.replace(/\\/g, '/');
    const mappedPortrait = normalizedGame === 'sts1' && cardId === 'CURSEOFTHEBELL'
      ? portraitFilename(normalizedGame, cardId)
      : null;
    const absoluteOutputPath = path.resolve(path.join(__dirname, '..', outputPath));
    const normalizedAbsoluteOutputPath = absoluteOutputPath.replace(/\\/g, '/');

    if (normalizedGame === 'sts1' && cardId === 'IMPULSE') {
      plan.push({
        game: normalizedGame,
        cardId,
        card,
        selector: selectorForGame(normalizedGame),
        outputPath,
        mappedPortrait,
        upgraded,
        status: 'skipped',
        reason: 'explicit_skip',
        detail: `IMPULSE is explicitly skipped because it is intentionally excluded from the export list.`,
      });
      continue;
    }

    if (upgraded && !cardHasUpgrade(card)) {
      plan.push({
        game: normalizedGame,
        cardId,
        card,
        selector: selectorForGame(normalizedGame),
        outputPath,
        mappedPortrait,
        upgraded,
        status: 'skipped',
        reason: 'no_upgrade',
        detail: `Card has no upgrade data: ${cardId}`,
      });
      continue;
    }

    if (safeExisting.has(normalizedOutputPath) || safeExisting.has(normalizedAbsoluteOutputPath)) {
      plan.push({
        game: normalizedGame,
        cardId,
        card,
        selector: selectorForGame(normalizedGame),
        outputPath,
        mappedPortrait,
        upgraded,
        status: 'skipped',
        reason: 'already_exists',
        detail: `Output already exists: ${outputPath}`,
      });
      continue;
    }

    plan.push({
      game: normalizedGame,
      cardId,
      card,
      selector: selectorForGame(normalizedGame),
      outputPath,
      mappedPortrait,
      upgraded,
      status: 'pending',
      reason: null,
      detail: null,
    });
  }

  return plan;
}

function summarizeExportResults(resultSet) {
  if (Array.isArray(resultSet)) {
    const total = resultSet.length;
    const exported = resultSet.filter((item) => item.status === 'success').length;
    const skipped = resultSet.filter((item) => item.status === 'skipped').length;
    const failed = resultSet.filter((item) => item.status === 'failed').length;
    const failedIds = resultSet
      .filter((item) => item.status === 'failed')
      .map((item) => item.cardId || item.id || item.card?.id)
      .filter(Boolean);
    const failedReasons = Object.fromEntries(
      resultSet
        .filter((item) => item.status === 'failed')
        .map((item) => [item.cardId || item.id || item.card?.id, item.reason || 'unknown_error'])
        .filter(([id]) => id)
    );

    return { total, exported, skipped, failed, failedIds, failedReasons };
  }

  const stats = resultSet || {};
  const failedIds = Array.isArray(stats.failedIds) ? stats.failedIds : [];
  const failedReasons = stats.failedReasons || {};
  const exported = Number(stats.exported ?? stats.success ?? 0);

  return {
    total: Number(stats.total || 0),
    exported,
    skipped: Number(stats.skipped || 0),
    failed: Number(stats.failed || 0),
    failedIds,
    failedReasons,
  };
}

async function runExportBatch(plan, exporter) {
  const results = [];
  const exportFn = typeof exporter === 'function' ? exporter : async () => ({ ok: true });

  for (const spec of Array.isArray(plan) ? plan : []) {
    if (!spec) {
      continue;
    }

    if (spec.status === 'skipped') {
      results.push({ ...spec, status: 'skipped' });
      continue;
    }

    try {
      const response = await exportFn(spec);
      const ok = response && response.ok !== false;
      results.push({
        ...spec,
        status: ok ? 'success' : 'failed',
        reason: ok ? null : (response && response.reason) || 'export_failed',
        detail: response && response.detail ? String(response.detail) : null,
      });
    } catch (error) {
      results.push({
        ...spec,
        status: 'failed',
        reason: (error && error.message) || String(error || 'unknown_error'),
        detail: (error && error.message) || String(error || 'unknown_error'),
      });
    }
  }

  return results;
}

module.exports = {
  SAMPLE_SPECS,
  buildExportPlan,
  browserLaunchOptions,
  cardHasUpgrade,
  checkRendererAvailability,
  clickUpgradeToggle,
  collectCardsForExport,
  exportAllCards,
  exportSamples,
  launchBrowser,
  parseArgs,
  portraitFilename,
  readPngDimensions,
  runExportBatch,
  selectorForGame,
  skipReason,
  summarizeExportResults,
  validateCaptureState,
  waitForUpgradedState,
};

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.stack ?? error}\n`);
    process.exitCode = 1;
  });
}
