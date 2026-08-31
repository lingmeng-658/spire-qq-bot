const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  buildExportPlan,
  checkRendererAvailability,
  collectCardsForExport,
  parseArgs,
  portraitFilename,
  readPngDimensions,
  runExportBatch,
  selectorForGame,
  skipReason,
  summarizeExportResults,
  validateCaptureState,
} = require('../scripts/export_card_samples.cjs');

function writeFixtureRawData(root) {
  const rawDir = path.join(root, 'data', 'raw');
  fs.mkdirSync(rawDir, { recursive: true });
  fs.writeFileSync(
    path.join(rawDir, 'sts1_cards.json'),
    JSON.stringify([
      { id: 'STRIKE_R', name: '打击', type: 'Attack', description: '造成6点伤害。' },
      { id: 'REBOUND', name: '弹回', type: 'Attack', description: '造成9点伤害。\n下一张牌放到抽牌堆顶。' },
      { id: 'CURSEOFTHEBELL', name: '铃铛的诅咒', type: 'Curse', description: '不能被打出。' },
      { id: 'IMPULSE', name: 'Impulse', type: 'Skill', description: '' },
    ]),
  );
  fs.writeFileSync(
    path.join(rawDir, 'sts2_cards.json'),
    JSON.stringify([
      { id: 'ABRASIVE', name: '磨蚀', type: 'Power', description: '获得1点敏捷。' },
      { id: 'ALIGNMENT', name: '星位序列', type: 'Skill', star_cost: 3, description: '获得[E]。' },
    ]),
  );
}

test('buildExportPlan selects only the four approved samples and writes PNG paths', () => {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'card-export-plan-'));
  writeFixtureRawData(projectRoot);

  const plan = buildExportPlan(projectRoot, path.join(projectRoot, 'data', 'images'));

  assert.deepEqual(
    plan.map(({ game, id, selector }) => ({ game, id, selector })),
    [
      { game: 'sts1', id: 'STRIKE_R', selector: '.cr1' },
      { game: 'sts1', id: 'REBOUND', selector: '.cr1' },
      { game: 'sts2', id: 'ABRASIVE', selector: '.cr' },
      { game: 'sts2', id: 'ALIGNMENT', selector: '.cr' },
    ],
  );
  assert.deepEqual(
    plan.map(({ outputPath }) => path.relative(projectRoot, outputPath)),
    [
      path.join('data', 'images', 'sts1', 'STRIKE_R.png'),
      path.join('data', 'images', 'sts1', 'REBOUND.png'),
      path.join('data', 'images', 'sts2', 'ABRASIVE.png'),
      path.join('data', 'images', 'sts2', 'ALIGNMENT.png'),
    ],
  );
});

test('portraitFilename handles the STS1 bell curse alias', () => {
  assert.equal(portraitFilename('sts1', 'CURSEOFTHEBELL'), 'curse_of_the_bell.png');
  assert.equal(portraitFilename('sts1', 'STRIKE_R'), 'strike_r.png');
  assert.equal(portraitFilename('sts2', 'ALIGNMENT'), 'alignment.png');
});

test('IMPULSE is skipped with an explicit data-quality reason', () => {
  assert.equal(
    skipReason('sts1', 'IMPULSE'),
    'missing portrait, empty description, and no Simplified Chinese localization',
  );
  assert.equal(skipReason('sts1', 'STRIKE_R'), null);
});

test('selectorForGame targets the card element rather than the page', () => {
  assert.equal(selectorForGame('sts1'), '.cr1');
  assert.equal(selectorForGame('sts2'), '.cr');
  assert.throws(() => selectorForGame('unknown'), /unsupported game/);
});

test('validateCaptureState rejects clipped or incomplete REBOUND text', () => {
  const sample = { game: 'sts1', id: 'REBOUND', description: '完整的中文描述' };

  assert.throws(
    () => validateCaptureState(sample, {
      descriptionText: '完整的中文描述',
      descriptionFits: false,
      imagesLoaded: true,
      fontsReady: true,
      isolated: true,
    }),
    /description is clipped/,
  );
  assert.throws(
    () => validateCaptureState(sample, {
      descriptionText: '中文描述',
      descriptionFits: true,
      imagesLoaded: true,
      fontsReady: true,
      isolated: true,
    }),
    /description text is incomplete/,
  );
});

test('validateCaptureState requires ALIGNMENT to show a 3-star cost', () => {
  const sample = { game: 'sts2', id: 'ALIGNMENT', description: '获得[E]。' };
  const baseState = {
    descriptionText: '获得。',
    descriptionFits: true,
    imagesLoaded: true,
    fontsReady: true,
    isolated: true,
  };

  assert.throws(
    () => validateCaptureState(sample, { ...baseState, starCost: '2' }),
    /expected star cost 3/,
  );
  assert.doesNotThrow(
    () => validateCaptureState(sample, { ...baseState, starCost: '3' }),
  );
});

test('validateCaptureState rejects a card that was not isolated from page chrome', () => {
  assert.throws(
    () => validateCaptureState(
      { game: 'sts2', id: 'ABRASIVE', description: '获得1点敏捷。' },
      {
        descriptionText: '获得1点敏捷。',
        descriptionFits: true,
        fontsReady: true,
        imagesLoaded: true,
        isolated: false,
      },
    ),
    /card element is not isolated/,
  );
});

test('parseArgs accepts --all for the full export CLI', () => {
  assert.deepEqual(parseArgs(['--all']), { all: true });
  assert.deepEqual(parseArgs(['--base-url', 'http://127.0.0.1:4324', '--all']), {
    'base-url': 'http://127.0.0.1:4324',
    all: true,
  });
});

test('checkRendererAvailability fails fast with a clear error when the local renderer is down', async () => {
  await assert.rejects(
    () => checkRendererAvailability('http://127.0.0.1:65535'),
    /Renderer is unavailable at http:\/\/127.0.0.1:65535/i,
  );
});

test('collectCardsForExport includes the full STS1 and STS2 plan by default', () => {
  const cards = [
    { id: 'A', type: 'Attack', description: 'A', color: 'ironclad' },
    { id: 'CURSEOFTHEBELL', type: 'Curse', description: '不能被打出。', color: 'curse' },
    { id: 'IMPULSE', type: 'Skill', description: '', color: 'ironclad' },
    { id: 'B', type: 'Power', description: 'B', color: 'ironclad' },
    { id: 'X', type: 'Skill', description: 'X', color: 'watcher' },
  ];

  const plan = collectCardsForExport('sts1', cards, new Set());
  assert.deepEqual(plan.map((item) => item.card.id), ['A', 'CURSEOFTHEBELL', 'IMPULSE', 'B', 'X']);
  assert.equal(plan[1].mappedPortrait, 'curse_of_the_bell.png');
  assert.equal(plan[1].status, 'pending');
  assert.equal(plan[2].status, 'skipped');
  assert.equal(plan[2].reason, 'explicit_skip');
});

test('collectCardsForExport skips existing image files', () => {
  const cards = [{ id: 'A', type: 'Attack', description: 'A', color: 'ironclad' }];

  const result = collectCardsForExport('sts1', cards, new Set(['data/images/sts1/A.png']));

  assert.equal(result[0].status, 'skipped');
  assert.equal(result[0].reason, 'already_exists');
});

test('single export error keeps processing the batch', async () => {
  const plan = [
    { game: 'sts1', card: { id: 'A' }, cardId: 'A', outputPath: 'data/images/sts1/A.png', selector: '.cr1' },
    { game: 'sts1', card: { id: 'B' }, cardId: 'B', outputPath: 'data/images/sts1/B.png', selector: '.cr1' },
  ];

  const calls = [];
  const results = await runExportBatch(plan, async (spec) => {
    calls.push(spec.cardId);
    if (spec.cardId === 'A') {
      throw new Error('boom');
    }
    return { ok: true, outputPath: spec.outputPath };
  });

  assert.deepEqual(calls, ['A', 'B']);
  assert.equal(results[0].status, 'failed');
  assert.equal(results[1].status, 'success');
});

test('summary contains totals and failed ids', () => {
  const summary = summarizeExportResults({
    total: 3,
    exported: 1,
    skipped: 1,
    failed: 1,
    failedIds: ['A'],
    failedReasons: { A: 'boom' },
  });

  assert.equal(summary.total, 3);
  assert.equal(summary.exported, 1);
  assert.equal(summary.skipped, 1);
  assert.equal(summary.failed, 1);
  assert.deepEqual(summary.failedIds, ['A']);
  assert.equal(summary.failedReasons.A, 'boom');
});

test('IMPULSE is explicitly skipped and CURSEOFTHEBELL is mapped', () => {
  const plan = collectCardsForExport('sts1', [
    { id: 'CURSEOFTHEBELL', type: 'Curse', description: '不能被打出。', color: 'curse' },
    { id: 'IMPULSE', type: 'Skill', description: '', color: 'ironclad' },
  ], new Set());

  assert.equal(plan[0].mappedPortrait, 'curse_of_the_bell.png');
  assert.equal(plan[1].status, 'skipped');
  assert.equal(plan[1].reason, 'explicit_skip');
});

test('readPngDimensions reads width and height from the PNG IHDR header', () => {
  const pngHeader = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(pngHeader);
  pngHeader.writeUInt32BE(816, 16);
  pngHeader.writeUInt32BE(1061, 20);

  assert.deepEqual(readPngDimensions(pngHeader), { width: 816, height: 1061 });
  assert.throws(() => readPngDimensions(Buffer.alloc(23)), /invalid PNG/);
});
