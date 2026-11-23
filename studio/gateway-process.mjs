import {spawn} from 'node:child_process';

const limit = Number(process.env.WEPPT_GATEWAY_CONCURRENCY ?? 4);
if (!Number.isInteger(limit) || limit < 1 || limit > 4) {
  throw new RangeError('WEPPT_GATEWAY_CONCURRENCY must be between 1 and 4');
}

let active = 0;
const interactiveQueue = [];
const backgroundQueue = [];
let lastWasBackground = true;

function release() {
  active--;
  const takeBackground = backgroundQueue.length && (!interactiveQueue.length || !lastWasBackground);
  const next = (takeBackground ? backgroundQueue : interactiveQueue).shift();
  if (next) next();
}

function acquire(signal, background) {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const queue = background ? backgroundQueue : interactiveQueue;
    function grant() {
      signal?.removeEventListener('abort', abort);
      active++;
      lastWasBackground = background;
      resolve();
    }
    function abort() {
      queue.splice(queue.indexOf(grant), 1);
      reject(signal.reason);
    }
    if (active < limit) return grant();
    queue.push(grant);
    signal?.addEventListener('abort', abort, {once: true});
  });
}

// All accounts and decks in this app process share these slots. A cancelled
// child still owns its slot until the operating system closes its pipes.
export async function runGatewayProcess(executable, args, options, {signal, background = false}, handleChild) {
  await acquire(signal, background);
  let child;
  try {
    signal?.throwIfAborted();
    child = spawn(executable, args, options);
  } catch (error) {
    release();
    throw error;
  }
  child.once('close', release);
  return handleChild(child);
}
