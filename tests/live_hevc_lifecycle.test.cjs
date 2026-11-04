/* Wall lease regressions exercise the actual private release helper offline. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/live.js'), 'utf8');
const begin = source.indexOf('function release(cells) {');
const end = source.indexOf('function disposePlayer(', begin);
assert.ok(begin >= 0 && end > begin, 'Read the actual wall lease release helper');
function wall(items) {
  const calls = [], players = new Map(items.map((item, index) => [index, item]));
  const release = vm.runInNewContext(source.slice(begin, end) + '\nrelease;', {
    players, consumer: 'a'.repeat(32),
    H: { api(url, options) { calls.push({ url, ...JSON.parse(JSON.stringify(options)) }); return Promise.resolve(); } },
  });
  return { release, calls };
}
const tile = (container = 'fmp4') => ({ camera_id: 'camera-17', stream: 'sub', container, serverRequested: true, closed: false });

test('a refused HEVC tile cannot release a shared stream before it acquires a lease', () => {
  const playing = tile(), refused = { ...tile(), closed: true, serverRequested: false };
  const w = wall([playing, refused]);
  w.release([refused]);
  assert.equal(w.calls.length, 0);
});

test('closing one duplicate tile retains the wall lease used by its sibling', () => {
  const closed = { ...tile(), closed: true }, playing = tile();
  const w = wall([closed, playing]);
  w.release([closed]);
  assert.equal(w.calls.length, 0);
  w.release([playing]);
  assert.equal(w.calls.length, 1);
  assert.equal(w.calls[0].body.container, 'fmp4');
});

test('closing the whole wall releases each distinct profile/container once', () => {
  const items = [tile(), tile(), tile('ts'), { ...tile(), stream: 'main' }];
  const w = wall(items);
  w.release(items);
  assert.equal(w.calls.length, 3);
  assert.deepEqual(w.calls.map(call => [call.body.stream, call.body.container]).sort(), [['main', 'fmp4'], ['sub', 'fmp4'], ['sub', 'ts']]);
  for (const call of w.calls) {
    assert.equal(call.url, '/api/live/stop');
    assert.equal(call.body.consumer, 'a'.repeat(32));
    assert.equal(call.keepalive, true);
  }
});

test('a TS sibling does not prevent releasing a distinct fMP4 container lease', () => {
  const fmp4 = { ...tile(), closed: true }, ts = tile('ts');
  const w = wall([fmp4, ts]);
  w.release([fmp4]);
  assert.equal(w.calls.length, 1);
  assert.equal(w.calls[0].body.container, 'fmp4');
});

test('live audio releases its separate TS lease without stopping video', () => {
  const w = wall([tile()]);
  w.release([{ camera_id: 'camera-17', stream: 'audio-sub' }]);
  assert.equal(w.calls.length, 1);
  assert.equal(w.calls[0].body.stream, 'audio-sub');
  assert.equal(w.calls[0].body.container, 'ts');
});
