#!/usr/bin/env node
/**
 * StockSentinel Node.js E2E Test Suite Runner Wrapper.
 * Invokes the Python test runner or reports test execution.
 */

const { spawn } = require('child_process');
const path = require('path');

const projectRoot = path.resolve(__dirname, '..');
const pythonRunner = path.join(__dirname, 'run_e2e.py');
const args = process.argv.slice(2);

console.log('StockSentinel Node E2E Runner delegating to Python E2E Runner...');
const child = spawn('python', [pythonRunner, ...args], {
  cwd: projectRoot,
  stdio: 'inherit'
});

child.on('error', (err) => {
  console.error(`Failed to start Python E2E runner: ${err.message}`);
  process.exit(1);
});

child.on('close', (code) => {
  process.exit(code);
});
