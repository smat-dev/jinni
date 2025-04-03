#!/usr/bin/env node
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import path from 'path';

// Get the directory of the current module (bin/cli.js)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Construct the absolute path to the Python CLI script
// Assumes cli.py is in ../jinni/ relative to this script (bin/cli.js)
const pythonScriptPath = path.resolve(__dirname, '..', 'jinni', 'cli.py');

// Determine the python executable name (python or python3)
// Simple check, might need refinement for edge cases or specific user setups
const pythonExecutable = process.platform === 'win32' ? 'python' : 'python3';

// Get command-line arguments passed to the Node script, excluding 'node' and the script path itself
const args = process.argv.slice(2);

// Spawn the Python script
const pythonProcess = spawn(pythonExecutable, [pythonScriptPath, ...args], {
  stdio: 'inherit', // Inherit stdin, stdout, stderr from the Node process
  // Ensure the environment includes necessary paths if Python dependencies are needed
  // env: { ...process.env, PYTHONPATH: path.resolve(__dirname, '..') } // Example if needed
});

// Handle process exit
pythonProcess.on('close', (code) => {
  process.exit(code ?? 0); // Exit Node process with the Python script's exit code
});

// Handle errors during spawning
pythonProcess.on('error', (err) => {
  console.error(`Failed to start Python script: ${err.message}`);
  process.exit(1);
});