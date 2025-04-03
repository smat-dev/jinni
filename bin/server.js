#!/usr/bin/env node
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import path from 'path';

// Get the directory of the current module (bin/server.js)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Construct the absolute path to the Python Server script
// Assumes server.py is in ../jinni/ relative to this script (bin/server.js)
const pythonScriptPath = path.resolve(__dirname, '..', 'jinni', 'server.py');

// Determine the python executable name (python or python3)
const pythonExecutable = process.platform === 'win32' ? 'python' : 'python3';

// Get command-line arguments passed to the Node script, excluding 'node' and the script path itself
// The MCP server might not need arguments passed this way, but we include the capability
const args = process.argv.slice(2);

// Spawn the Python script
// MCP servers typically communicate via stdio, so 'inherit' is appropriate
const pythonProcess = spawn(pythonExecutable, [pythonScriptPath, ...args], {
  stdio: 'inherit',
  // Ensure the environment includes necessary paths if Python dependencies are needed
  // env: { ...process.env, PYTHONPATH: path.resolve(__dirname, '..') } // Example if needed
});

// Handle process exit
pythonProcess.on('close', (code) => {
  // Log server exit, maybe? Or just exit silently.
  console.error(`Python server script exited with code ${code}`);
  process.exit(code ?? 0); // Exit Node process with the Python script's exit code
});

// Handle errors during spawning
pythonProcess.on('error', (err) => {
  console.error(`Failed to start Python server script: ${err.message}`);
  process.exit(1);
});