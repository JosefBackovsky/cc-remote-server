import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { generate, extractServiceVolumes, nameFromRepo, parseRepoArg } from '../src/generator.js';

describe('extractServiceVolumes', () => {
  it('extracts named volumes from services', () => {
    const services = {
      db: { image: 'postgres:16', volumes: ['pgdata:/var/lib/postgresql/data'] },
    };
    const result = extractServiceVolumes(services);
    assert.deepEqual(result, { pgdata: true });
  });

  it('ignores bind mounts', () => {
    const services = {
      app: { image: 'node:22', volumes: ['./src:/app', '/host/path:/container'] },
    };
    const result = extractServiceVolumes(services);
    assert.deepEqual(result, {});
  });

  it('handles services without volumes', () => {
    const services = {
      redis: { image: 'redis:7' },
    };
    const result = extractServiceVolumes(services);
    assert.deepEqual(result, {});
  });
});

describe('generate', () => {
  let outputDir;

  beforeEach(() => {
    outputDir = mkdtempSync(join(tmpdir(), 'devcontainer-test-'));
  });

  afterEach(() => {
    rmSync(outputDir, { recursive: true, force: true });
  });

  const baseOptions = {
    name: 'testproject',
    repos: [{ url: 'git@github.com:test/repo.git', branch: 'main', name: 'repo' }],
    multiRepo: false,
    stacks: ['nodejs'],
    services: [],
    output: undefined,
  };

  function opts(overrides = {}) {
    return { ...baseOptions, output: outputDir, ...overrides };
  }

  const multiRepoOptions = {
    name: 'docbro',
    repos: [
      { url: 'https://github.com/org/docbro-be.git', branch: 'main', name: 'docbro-be' },
      { url: 'https://github.com/org/docbro-fe.git', branch: 'develop', name: 'docbro-fe' },
    ],
    multiRepo: true,
    stacks: ['nodejs'],
    services: [],
    output: undefined,
  };

  function multiOpts(overrides = {}) {
    return { ...multiRepoOptions, output: outputDir, ...overrides };
  }

  // --- Basic output structure ---

  it('creates all output files in correct structure', () => {
    generate(opts());
    const devcontainerDir = join(outputDir, '.devcontainer');
    assert.ok(existsSync(join(outputDir, 'project.yml')));
    assert.ok(existsSync(join(devcontainerDir, 'init.sh')));
    assert.ok(existsSync(join(devcontainerDir, 'init-firewall.sh')));
    assert.ok(existsSync(join(devcontainerDir, 'Dockerfile')));
    assert.ok(existsSync(join(devcontainerDir, 'docker-compose.yml')));
    assert.ok(existsSync(join(devcontainerDir, 'devcontainer.json')));
  });

  it('project.yml contains repo and branch', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, 'project.yml'), 'utf-8');
    assert.ok(content.includes('git@github.com:test/repo.git'));
    assert.ok(content.includes('branch: main'));
  });

  it('shell scripts have executable permissions', () => {
    generate(opts());
    const devcontainerDir = join(outputDir, '.devcontainer');
    const initMode = statSync(join(devcontainerDir, 'init.sh')).mode;
    assert.ok(initMode & 0o100, 'init.sh should be executable');
    const firewallMode = statSync(join(devcontainerDir, 'init-firewall.sh')).mode;
    assert.ok(firewallMode & 0o100, 'init-firewall.sh should be executable');
  });

  it('init.sh references correct repo URL', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'init.sh'), 'utf-8');
    assert.ok(content.includes('git@github.com:test/repo.git'));
    assert.ok(content.includes('testproject'));
  });

  // --- Stacks ---

  it('nodejs stack uses node:22 base image', () => {
    generate(opts({ stacks: ['nodejs'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(content.startsWith('FROM node:22'));
  });

  it('python stack uses python base image', () => {
    generate(opts({ stacks: ['python'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(content.startsWith('FROM python:3.12'));
  });

  it('dotnet stack uses dotnet base image', () => {
    generate(opts({ stacks: ['dotnet'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(content.startsWith('FROM mcr.microsoft.com/dotnet/sdk:'));
  });

  it('devcontainer.json has base extensions for any stack', () => {
    generate(opts({ stacks: ['nodejs'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    const ext = json.customizations.vscode.extensions;
    assert.ok(ext.includes('anthropic.claude-code'));
    assert.ok(ext.includes('dbaeumer.vscode-eslint'));
    assert.ok(ext.includes('esbenp.prettier-vscode'));
    assert.ok(ext.includes('eamodio.gitlens'));
    assert.ok(ext.includes('streetsidesoftware.code-spell-checker'));
  });

  it('nodejs stack has jest extension', () => {
    generate(opts({ stacks: ['nodejs'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.ok(json.customizations.vscode.extensions.includes('orta.vscode-jest'));
  });

  it('python stack has python extension', () => {
    generate(opts({ stacks: ['python'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.ok(json.customizations.vscode.extensions.includes('ms-python.python'));
  });

  // --- Services ---

  it('no services when none selected', () => {
    generate(opts({ services: [] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(!content.includes('postgres:17'));
    assert.ok(!content.includes('redis:7'));
  });

  it('postgres service included when selected', () => {
    generate(opts({ services: ['postgres'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('postgres:17'));
    assert.ok(content.includes('pgdata:'));
  });

  it('redis service included when selected', () => {
    generate(opts({ services: ['redis'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('redis:7'));
  });

  it('mongo service included when selected', () => {
    generate(opts({ services: ['mongo'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('mongo:7'));
    assert.ok(content.includes('mongodata:'));
  });

  it('azurite service included when selected', () => {
    generate(opts({ services: ['azurite'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('azurite'));
    assert.ok(content.includes('azuritedata:'));
  });

  it('multiple services can be combined', () => {
    generate(opts({ services: ['postgres', 'redis', 'azurite'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('postgres:17'));
    assert.ok(content.includes('redis:7'));
    assert.ok(content.includes('azurite'));
  });

  it('docker-compose.yml has correct project-named volumes', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('testproject-commandhistory:'));
    assert.ok(content.includes('claude-shared:'));
    assert.ok(!content.includes('testproject-claude-project:'));
  });

  it('docker-compose.yml uses devcontainer as service name', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('devcontainer:'));
    assert.ok(!content.includes('  app:'));
  });

  it('devcontainer.json references devcontainer service', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.equal(json.service, 'devcontainer');
  });

  // --- Firewall ---

  it('init-firewall.sh uses proxy-mode (no domain names, allows Docker networks)', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'init-firewall.sh'), 'utf-8');
    // Proxy-mode: allows Docker internal networks, blocks everything else
    assert.ok(content.includes('10.0.0.0/8'));
    assert.ok(content.includes('172.16.0.0/12'));
    assert.ok(content.includes('192.168.0.0/16'));
    assert.ok(content.includes('127.0.0.11'));
    // Should NOT contain domain names (proxy handles that)
    assert.ok(!content.includes('api.anthropic.com'));
    assert.ok(!content.includes('registry.npmjs.org'));
  });

  // --- Full internet mode ---

  it('fullInternet skips firewall script', () => {
    generate(opts({ fullInternet: true }));
    assert.ok(!existsSync(join(outputDir, '.devcontainer', 'init-firewall.sh')));
  });

  it('fullInternet removes NET_ADMIN from docker-compose', () => {
    generate(opts({ fullInternet: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(!content.includes('NET_ADMIN'));
  });

  it('fullInternet removes postStartCommand from devcontainer.json', () => {
    generate(opts({ fullInternet: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.equal(json.postStartCommand, undefined);
    assert.equal(json.waitFor, undefined);
  });

  it('fullInternet removes iptables from Dockerfile', () => {
    generate(opts({ fullInternet: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(!content.includes('iptables'));
    assert.ok(!content.includes('init-firewall.sh'));
  });

  // --- Local Claude ---

  it('no .claude mount without localClaude', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(!content.includes('/workspace/.claude'));
    assert.ok(!content.includes('.project-claude'));
  });

  it('localClaude creates .project-claude directory', () => {
    generate(opts({ localClaude: true }));
    assert.ok(existsSync(join(outputDir, '.project-claude')));
  });

  it('localClaude adds bind-mount for .claude', () => {
    generate(opts({ localClaude: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('.project-claude:/workspace/.claude:cached'));
  });

  it('localClaude adds .claude to git exclude in init.sh', () => {
    generate(opts({ localClaude: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'init.sh'), 'utf-8');
    assert.ok(content.includes('.claude/'));
    assert.ok(content.includes('exclude'));
  });

  it('no git exclude without localClaude', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'init.sh'), 'utf-8');
    assert.ok(!content.includes('exclude'));
  });

  // --- SSH server ---

  it('Dockerfile contains openssh-server', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(content.includes('openssh-server'));
  });

  it('docker-compose.yml contains sshd in command', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('sshd'));
  });

  it('docker-compose.yml contains default SSH port 2222:22', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('2222:22'));
  });

  it('custom SSH port is propagated to docker-compose.yml', () => {
    generate(opts({ sshPort: 3333 }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('3333:22'));
    assert.ok(!content.includes('2222:22'));
  });

  // --- Port forwarding ---

  it('forwardPorts contains SSH port without services', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.deepEqual(json.forwardPorts, [2222]);
  });

  it('forwardPorts uses custom SSH port', () => {
    generate(opts({ sshPort: 3333 }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.deepEqual(json.forwardPorts, [3333]);
  });

  it('forwardPorts includes service ports', () => {
    generate(opts({ services: ['postgres', 'redis'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.ok(json.forwardPorts.includes(2222));
    assert.ok(json.forwardPorts.includes(5432));
    assert.ok(json.forwardPorts.includes(6379));
  });

  it('portsAttributes has SSH label', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.equal(json.portsAttributes['2222'].label, 'SSH');
    assert.equal(json.portsAttributes['2222'].onAutoForward, 'silent');
  });

  it('portsAttributes has service labels', () => {
    generate(opts({ services: ['postgres', 'redis'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.equal(json.portsAttributes['5432'].label, 'PostgreSQL');
    assert.equal(json.portsAttributes['6379'].label, 'Redis');
  });

  it('azurite multi-port forwarding', () => {
    generate(opts({ services: ['azurite'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.ok(json.forwardPorts.includes(10000));
    assert.ok(json.forwardPorts.includes(10001));
    assert.ok(json.forwardPorts.includes(10002));
    assert.equal(json.portsAttributes['10000'].label, 'Azurite (Azure Storage Emulator)');
  });

  it('otherPortsAttributes remains ignore', () => {
    generate(opts({ services: ['postgres'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.equal(json.otherPortsAttributes.onAutoForward, 'ignore');
  });

  // --- Git credentials isolation ---

  it('devcontainer.json has remoteEnv to block VS Code git credential forwarding', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.equal(json.remoteEnv.VSCODE_GIT_ASKPASS_MAIN, '');
    assert.equal(json.remoteEnv.VSCODE_GIT_ASKPASS_NODE, '');
    assert.equal(json.remoteEnv.VSCODE_GIT_ASKPASS_EXTRA_ARGS, '');
    assert.equal(json.remoteEnv.VSCODE_GIT_IPC_HANDLE, '');
    assert.equal(json.remoteEnv.GIT_ASKPASS, '');
  });

  it('devcontainer.json disables git.terminalAuthentication', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.equal(json.customizations.vscode.settings['git.terminalAuthentication'], false);
  });

  it('devcontainer.json sets gitCredentialHelperConfigLocation to none', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    assert.equal(json.customizations.vscode.settings['dev.containers.gitCredentialHelperConfigLocation'], 'none');
  });

  it('Dockerfile sets git credential.helper to store', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(content.includes("credential.helper 'store --file /home/node/.persistent/.git-credentials'"));
  });

  it('git proxy config in Dockerfile when not fullInternet', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(content.includes('http.proxy http://firewall:3128'));
    assert.ok(content.includes('https.proxy http://firewall:3128'));
  });

  it('no git proxy config when fullInternet', () => {
    generate(opts({ fullInternet: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(!content.includes('http.proxy'));
    assert.ok(content.includes('credential.helper'));
  });

  it('dnsutils NOT in Dockerfile', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(!content.includes('dnsutils'));
  });

  // --- Include compose ---

  it('no include section by default', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(!content.includes('include:'));
  });

  it('includeCompose adds include section with project compose path', () => {
    generate(opts({ includeCompose: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('include:'));
    assert.ok(content.includes('../../testproject/docker-compose.yml'));
  });

  // --- Firewall proxy service ---

  it('firewall service in docker-compose when not fullInternet', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('firewall:'));
    assert.ok(content.includes('josefbackovsky/cc-remote-firewall:latest'));
    assert.ok(content.includes('firewall-data:/data'));
    assert.ok(content.includes('8180:8080'), 'default firewall port should be 8180');
  });

  it('firewall service NOT in docker-compose when fullInternet', () => {
    generate(opts({ fullInternet: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(!content.includes('cc-remote-firewall'));
    assert.ok(!content.includes('firewall-data'));
  });

  it('proxy env vars in devcontainer when not fullInternet', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('http_proxy=http://firewall:3128'));
    assert.ok(content.includes('https_proxy=http://firewall:3128'));
    assert.ok(content.includes('HTTP_PROXY=http://firewall:3128'));
    assert.ok(content.includes('HTTPS_PROXY=http://firewall:3128'));
  });

  it('no_proxy contains firewall service name', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('no_proxy=localhost,127.0.0.1,firewall'));
  });

  it('no_proxy includes service names', () => {
    generate(opts({ services: ['postgres', 'redis'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('no_proxy=localhost,127.0.0.1,firewall,postgres,redis'));
  });

  it('no proxy env vars when fullInternet', () => {
    generate(opts({ fullInternet: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(!content.includes('http_proxy'));
    assert.ok(!content.includes('https_proxy'));
  });

  it('devcontainer depends_on firewall when not fullInternet', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('depends_on:'));
    assert.ok(content.includes('condition: service_healthy'));
  });

  it('firewall-data volume in volumes section', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('firewall-data:'));
  });

  it('firewall healthcheck defined', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('healthcheck:'));
    assert.ok(content.includes('start_period:'));
  });

  it('EXTRA_DOMAINS not set when stack has no firewall_domains', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(!content.includes('EXTRA_DOMAINS'));
  });

  // --- CLAUDE.md ---

  it('CLAUDE.md generated with proxy instructions when not fullInternet', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'CLAUDE.md'), 'utf-8');
    assert.ok(content.includes('Proxy & Firewall Instructions'));
    assert.ok(content.includes('firewall:8080'));
    assert.ok(content.includes('/api/request'));
  });

  it('CLAUDE.md NOT generated when fullInternet', () => {
    generate(opts({ fullInternet: true }));
    assert.ok(!existsSync(join(outputDir, '.devcontainer', 'CLAUDE.md')));
  });

  // --- Multi-repo ---

  it('multi-repo project.yml uses repos list format', () => {
    generate(multiOpts());
    const content = readFileSync(join(outputDir, 'project.yml'), 'utf-8');
    assert.ok(content.includes('repos:'));
    assert.ok(content.includes('url: https://github.com/org/docbro-be.git'));
    assert.ok(content.includes('branch: main'));
    assert.ok(content.includes('url: https://github.com/org/docbro-fe.git'));
    assert.ok(content.includes('branch: develop'));
    assert.ok(!content.includes('repo:'));
  });

  it('multi-repo init.sh clones each repo into subdirectory', () => {
    generate(multiOpts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'init.sh'), 'utf-8');
    assert.ok(content.includes('mkdir -p'));
    assert.ok(content.includes('docbro-be'));
    assert.ok(content.includes('docbro-fe'));
    assert.ok(content.includes('https://github.com/org/docbro-be.git'));
    assert.ok(content.includes('https://github.com/org/docbro-fe.git'));
    assert.ok(content.includes('--branch main'));
    assert.ok(content.includes('--branch develop'));
  });

  it('multi-repo docker-compose mounts each repo as /workspace/<repoName>', () => {
    generate(multiOpts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('docbro/docbro-be:/workspace/docbro-be:cached'));
    assert.ok(content.includes('docbro/docbro-fe:/workspace/docbro-fe:cached'));
    assert.ok(!content.includes('docbro:/workspace:cached'));
  });

  it('multi-repo with includeCompose does NOT include compose files', () => {
    generate(multiOpts({ includeCompose: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(!content.includes('include:'));
  });

  it('single-repo with includeCompose still includes compose', () => {
    generate(opts({ includeCompose: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('include:'));
    assert.ok(content.includes('../../testproject/docker-compose.yml'));
  });

  it('multi-repo with localClaude adds git exclude per repo in init.sh', () => {
    generate(multiOpts({ localClaude: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'init.sh'), 'utf-8');
    assert.ok(content.includes('.claude/'));
    assert.ok(content.includes('exclude'));
    assert.ok(content.includes('docbro-be/.git/info/exclude'));
    assert.ok(content.includes('docbro-fe/.git/info/exclude'));
  });

  it('multi-repo with localClaude mounts .project-claude to /workspace/.claude', () => {
    generate(multiOpts({ localClaude: true }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('.project-claude:/workspace/.claude:cached'));
  });

  it('multi-repo with fullInternet skips firewall', () => {
    generate(multiOpts({ fullInternet: true }));
    const compose = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(!compose.includes('NET_ADMIN'));
    assert.ok(!compose.includes('http_proxy'));
    assert.ok(compose.includes('docbro/docbro-be:/workspace/docbro-be:cached'));
    assert.ok(compose.includes('docbro/docbro-fe:/workspace/docbro-fe:cached'));
    assert.ok(!existsSync(join(outputDir, '.devcontainer', 'init-firewall.sh')));
  });

  it('multi-repo with services includes no_proxy with service names', () => {
    generate(multiOpts({ services: ['postgres', 'redis'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('no_proxy=localhost,127.0.0.1,firewall,postgres,redis'));
    assert.ok(content.includes('docbro/docbro-be:/workspace/docbro-be:cached'));
  });

  it('multi-repo init.sh checks each repo directory individually', () => {
    generate(multiOpts());
    const content = readFileSync(join(outputDir, '.devcontainer', 'init.sh'), 'utf-8');
    const dirChecks = content.match(/\[ -d .+\]/g) || [];
    assert.ok(dirChecks.length >= 2, 'Should have at least 2 directory checks for 2 repos');
  });

  it('single-repo project.yml uses flat format (not repos list)', () => {
    generate(opts());
    const content = readFileSync(join(outputDir, 'project.yml'), 'utf-8');
    assert.ok(content.includes('repo:'));
    assert.ok(content.includes('branch:'));
    assert.ok(!content.includes('repos:'));
  });

  // --- Port prefix ---

  it('custom firewallPort is propagated to docker-compose.yml', () => {
    generate(opts({ firewallPort: 8280 }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('8280:8080'));
    assert.ok(!content.includes('8180:8080'));
  });

  it('port-prefix sets both SSH and firewall ports', () => {
    generate(opts({ sshPort: 8222, firewallPort: 8280 }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'docker-compose.yml'), 'utf-8');
    assert.ok(content.includes('8222:22'));
    assert.ok(content.includes('8280:8080'));
  });

  // --- Multi-stack ---

  it('multi-stack merges vscode extensions from all stacks', () => {
    generate(opts({ stacks: ['python', 'nodejs'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'devcontainer.json'), 'utf-8');
    const json = JSON.parse(content);
    const ext = json.customizations.vscode.extensions;
    // Python extensions
    assert.ok(ext.includes('ms-python.python'));
    // Node.js extensions
    assert.ok(ext.includes('orta.vscode-jest'));
  });

  it('multi-stack uses first stack base image', () => {
    generate(opts({ stacks: ['python', 'nodejs'] }));
    const content = readFileSync(join(outputDir, '.devcontainer', 'Dockerfile'), 'utf-8');
    assert.ok(content.startsWith('FROM python:3.12'));
  });
});

describe('nameFromRepo', () => {
  it('extracts name from SSH URL', () => {
    assert.equal(nameFromRepo('git@github.com:zakaznik/mujprojekt.git'), 'mujprojekt');
  });

  it('extracts name from HTTPS URL', () => {
    assert.equal(nameFromRepo('https://github.com/zakaznik/mujprojekt.git'), 'mujprojekt');
  });

  it('handles URL without .git suffix', () => {
    assert.equal(nameFromRepo('https://github.com/zakaznik/mujprojekt'), 'mujprojekt');
  });

  it('throws on empty result', () => {
    assert.throws(() => nameFromRepo(''), /Cannot derive/);
  });
});

describe('parseRepoArg', () => {
  it('parses HTTPS URL without branch', () => {
    const result = parseRepoArg('https://github.com/org/repo.git');
    assert.deepEqual(result, { url: 'https://github.com/org/repo.git', branch: 'main', name: 'repo' });
  });

  it('parses HTTPS URL with #branch', () => {
    const result = parseRepoArg('https://github.com/org/repo.git#develop');
    assert.deepEqual(result, { url: 'https://github.com/org/repo.git', branch: 'develop', name: 'repo' });
  });

  it('parses SSH URL with #branch', () => {
    const result = parseRepoArg('git@github.com:org/repo.git#feature', 'main');
    assert.deepEqual(result, { url: 'git@github.com:org/repo.git', branch: 'feature', name: 'repo' });
  });

  it('uses custom defaultBranch when no #branch', () => {
    const result = parseRepoArg('https://github.com/org/repo.git', 'develop');
    assert.deepEqual(result, { url: 'https://github.com/org/repo.git', branch: 'develop', name: 'repo' });
  });

  it('falls back to defaultBranch when #branch is empty', () => {
    const result = parseRepoArg('https://github.com/org/repo.git#');
    assert.deepEqual(result, { url: 'https://github.com/org/repo.git', branch: 'main', name: 'repo' });
  });

  it('per-repo #branch overrides global defaultBranch', () => {
    const result = parseRepoArg('https://github.com/org/repo.git#main', 'develop');
    assert.equal(result.branch, 'main');
  });

  it('repo without #branch uses global defaultBranch', () => {
    const result = parseRepoArg('https://github.com/org/repo.git', 'develop');
    assert.equal(result.branch, 'develop');
  });
});
