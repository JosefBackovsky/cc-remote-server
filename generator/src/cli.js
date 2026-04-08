#!/usr/bin/env node

import { Command } from 'commander';
import { generate, printInstructions, parseRepoArg } from './generator.js';

const program = new Command();

program
  .name('devcontainer-generator')
  .description('Generate devcontainer repositories with Claude Code sandbox')
  .option('--name <name>', 'Project name (derived from repo URL if omitted)')
  .option('--repo <url>', 'Git repository URL (repeatable, #branch for per-repo branch)', (val, prev) => (prev || []).concat([val]))
  .option('--branch <branch>', 'Default git branch (default: main)')
  .option('--stack <stack>', 'SDK/runtime stack (repeatable, first = base image, default: nodejs)', (val, prev) => (prev || []).concat([val]))
  .option('--services <services>', 'Comma-separated services: postgres, mongo, redis, azurite')
  .option('--full-internet', 'Allow full internet access (skip firewall)')
  .option('--no-ungit', 'Disable Ungit web git GUI (enabled by default for git push isolation)')
  .option('--include-compose', 'Include project docker-compose.yml via compose include')
  .option('--local-claude', 'Mount .claude from devcontainer repo instead of Docker volume')
  .option('--ssh-port <port>', 'SSH port for JetBrains IDE access (default: 2222)')
  .option('--port-prefix <prefix>', 'Port prefix for all exposed ports (e.g. 82 → SSH 8222, firewall 8280)')
  .option('--git-name <name>', 'Git user.name for commits')
  .option('--git-email <email>', 'Git user.email for commits')
  .requiredOption('--output <path>', 'Output directory path')
  .action((options) => {
    try {
      // Validace: min. 1 repo
      const repoArgs = options.repo || [];
      if (repoArgs.length === 0) {
        console.error('Error: At least one --repo is required');
        process.exit(1);
      }

      const defaultBranch = options.branch || 'main';
      const repos = repoArgs.map(r => parseRepoArg(r, defaultBranch));
      const multiRepo = repos.length > 1;

      // Validace: --name povinný při multi-repo
      if (multiRepo && !options.name) {
        console.error('Error: --name is required when specifying multiple repositories');
        process.exit(1);
      }

      // Validace: unikátní repo názvy
      const repoNames = repos.map(r => r.name);
      const duplicates = repoNames.filter((n, i) => repoNames.indexOf(n) !== i);
      if (duplicates.length > 0) {
        console.error(`Error: Duplicate repository name '${duplicates[0]}' — each repo must have a unique basename`);
        process.exit(1);
      }

      // Odvození názvu pro single-repo
      if (!options.name) {
        options.name = repos[0].name;
      }

      const services = (options.services || '').split(',').map(s => s.trim()).filter(Boolean);

      let sshPort, firewallPort, ungitPort;
      if (options.portPrefix) {
        sshPort = parseInt(options.portPrefix + '22', 10);
        firewallPort = parseInt(options.portPrefix + '80', 10);
        ungitPort = parseInt(options.portPrefix + '04', 10);
      } else {
        sshPort = parseInt(options.sshPort || '2222', 10);
        firewallPort = 8180;
        ungitPort = 8004;
      }

      const stacks = (options.stack && options.stack.length > 0) ? options.stack : ['nodejs'];
      const ungit = options.ungit !== false;
      generate({ ...options, repos, multiRepo, stacks, services, sshPort, firewallPort, ungitPort, ungit });
      printInstructions(options.name, options.output, { localClaude: options.localClaude, sshPort, ungitPort, ungit, repos, multiRepo, includeCompose: options.includeCompose });
    } catch (err) {
      console.error(`Error: ${err.message}`);
      process.exit(1);
    }
  });

program.parse();
