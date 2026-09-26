import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { connect } from 'node:net';
import { resolve } from 'node:path';

const dockerfile = await readFile(resolve('Dockerfile'), 'utf8');
const command = JSON.parse(dockerfile.match(/^CMD (\[.*\])$/m)?.[1] ?? 'null');
assert.ok(Array.isArray(command), 'Dockerfile must have a JSON-array CMD');

const fixture = {
  version: 1,
  viewer: { personId: 'PSN-00001', displayName: 'Runtime Viewer' },
  personContexts: [{ type: 'PERSON', personId: 'PSN-00001', displayName: 'Runtime Viewer' }],
  circleContexts: [],
  careRelationships: [],
};

async function freePort() {
  const server = createServer();
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  const port = server.address().port;
  await new Promise((done) => server.close(done));
  return port;
}

async function startBff() {
  const server = createServer((request, response) => {
    if (request.url !== '/bootstrap') return response.writeHead(404).end();
    if (request.headers.cookie !== 'episteck_home_session=runtime-session') {
      return response.writeHead(401).end();
    }
    response.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(fixture));
  });
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  return server;
}

function launch(port, bffPort, overrides = {}) {
  const env = {
    ...process.env,
    NODE_ENV: 'production',
    HOME_HUB_DATA_MODE: 'LIVE',
    HOME_HUB_BFF_BASE_URL: `http://127.0.0.1:${bffPort}`,
    HOME_HUB_PUBLIC_ORIGIN: `http://127.0.0.1:${port}`,
    HOSTNAME: '127.0.0.1',
    PORT: String(port),
  };
  for (const [name, value] of Object.entries(overrides)) {
    if (value === undefined) delete env[name];
    else env[name] = value;
  }
  const child = spawn(command[0], command.slice(1), {
    cwd: resolve('.next/standalone'),
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  child.stdout.on('data', (chunk) => { output += chunk; });
  child.stderr.on('data', (chunk) => { output += chunk; });
  const exit = new Promise((done) => child.once('exit', (code, signal) => done({ code, signal })));
  return { child, exit, output: () => output };
}

function portProbe(port) {
  return new Promise((done) => {
    const socket = connect({ host: '127.0.0.1', port });
    socket.once('connect', () => { socket.destroy(); done(true); });
    socket.once('error', () => done(false));
  });
}

async function stop(child, exit) {
  if (child.exitCode === null) child.kill();
  await exit;
}

async function rejectsBeforeListen(label, bffPort, overrides) {
  const port = await freePort();
  const running = launch(port, bffPort, overrides);
  let opened = false;
  const probe = setInterval(async () => { opened ||= await portProbe(port); }, 15);
  let timeout;
  const outcome = await Promise.race([
    running.exit,
    new Promise((done) => { timeout = setTimeout(() => done({ code: null, signal: 'timeout' }), 5_000); }),
  ]);
  clearTimeout(timeout);
  clearInterval(probe);
  await portProbe(port).then((isOpen) => { opened ||= isOpen; });
  if (outcome.signal === 'timeout') await stop(running.child, running.exit);
  assert.equal(opened, false, `${label}: TCP listener opened before validation`);
  assert.notEqual(outcome.signal, 'timeout', `${label}: startup did not exit; ${running.output()}`);
  assert.ok(Number.isInteger(outcome.code) && outcome.code !== 0,
    `${label}: startup must exit with a non-zero code; ${running.output()}`);
  assert.match(running.output(), /FATAL: HOME_HUB_/, `${label}: missing config error`);
  process.stdout.write(`${label}: non-zero exit before listen\n`);
}

const bff = await startBff();
try {
  const bffPort = bff.address().port;
  for (const [label, overrides] of [
    ['missing mode', { HOME_HUB_DATA_MODE: undefined }],
    ['MOCK mode', { HOME_HUB_DATA_MODE: 'MOCK' }],
    ['missing BFF URL', { HOME_HUB_BFF_BASE_URL: undefined }],
    ['untrusted BFF URL', { HOME_HUB_BFF_BASE_URL: 'https://remote.example.test' }],
    ['missing public origin', { HOME_HUB_PUBLIC_ORIGIN: undefined }],
    ['untrusted public origin', { HOME_HUB_PUBLIC_ORIGIN: 'http://remote.example.test' }],
    ['malformed public origin', { HOME_HUB_PUBLIC_ORIGIN: 'not a URL' }],
  ]) {
    await rejectsBeforeListen(label, bffPort, overrides);
  }

  const port = await freePort();
  const running = launch(port, bffPort);
  try {
    let opened = false;
    for (let attempt = 0; attempt < 1_500 && !opened; attempt++) {
      opened = await portProbe(port);
      if (!opened) await new Promise((done) => setTimeout(done, 20));
    }
    assert.equal(opened, true, `valid config did not listen: ${running.output()}`);
    const authenticated = await fetch(`http://127.0.0.1:${port}/app`, {
      headers: { Cookie: 'episteck_home_session=runtime-session' },
      redirect: 'manual',
    });
    assert.equal(authenticated.status, 200, running.output());
    assert.match(await authenticated.text(), /Runtime Viewer/);
    const anonymous = await fetch(`http://127.0.0.1:${port}/app`, { redirect: 'manual' });
    assert.equal(anonymous.status, 307);
    assert.equal(anonymous.headers.get('location'), `http://127.0.0.1:${port}/login`);
    process.stdout.write('valid runtime overrides: listener and bootstrap passed\n');
  } finally {
    await stop(running.child, running.exit);
  }
} finally {
  await new Promise((done) => bff.close(done));
}
