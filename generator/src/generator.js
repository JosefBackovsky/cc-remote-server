import { mkdirSync, writeFileSync, chmodSync, existsSync } from 'node:fs';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import ejs from 'ejs';
import { loadStack, loadAndMergeStacks, loadServices } from './stack-loader.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const TEMPLATES_DIR = join(__dirname, 'templates', 'base');

/**
 * Odvodí název projektu z repo URL.
 * git@github.com:zakaznik/mujprojekt.git → mujprojekt
 * https://github.com/zakaznik/mujprojekt.git → mujprojekt
 */
export function nameFromRepo(repoUrl) {
  const basename = repoUrl.split('/').pop().replace(/\.git$/, '');
  if (!basename) {
    throw new Error(`Cannot derive project name from repo URL: ${repoUrl}`);
  }
  return basename;
}

/**
 * Parsuje repo argument s volitelným #branch suffixem.
 * "https://github.com/org/repo.git#develop" → { url, branch: "develop", name: "repo" }
 * "git@github.com:org/repo.git" → { url, branch: defaultBranch, name: "repo" }
 */
export function parseRepoArg(repoArg, defaultBranch = 'main') {
  const hashIndex = repoArg.lastIndexOf('#');
  let url, branch;
  if (hashIndex > 0) {
    url = repoArg.substring(0, hashIndex);
    branch = repoArg.substring(hashIndex + 1);
  } else {
    url = repoArg;
    branch = defaultBranch;
  }
  // Prázdný branch za # (např. "repo.git#") → fallback na default
  if (!branch) {
    branch = defaultBranch;
  }
  const name = nameFromRepo(url);
  return { url, branch, name };
}

/**
 * Extrahuje pojmenované volumes ze služeb (ne bind-mount cesty).
 * Např. "pgdata:/var/lib/postgresql/data" → { pgdata: true }
 */
export function extractServiceVolumes(services) {
  const volumes = {};

  for (const svc of Object.values(services)) {
    if (!svc.volumes) continue;
    for (const vol of svc.volumes) {
      const source = vol.split(':')[0];
      // Pojmenovaný volume nemá / na začátku ani . na začátku
      if (!source.startsWith('/') && !source.startsWith('.')) {
        volumes[source] = true;
      }
    }
  }

  return volumes;
}

function renderTemplate(templateName, context) {
  const templatePath = join(TEMPLATES_DIR, templateName);
  const template = readFileSync(templatePath, 'utf-8');
  return ejs.render(template, context, { filename: templatePath });
}

/**
 * Generuje kompletní devcontainer repo do output adresáře.
 */
export function generate(options) {
  const { name, repos, multiRepo = false, stacks: stackNames = ['nodejs'], services: selectedServices = [], fullInternet = false, includeCompose = false, localClaude = false, ungit = true, sshPort = 2222, firewallPort = 8180, ungitPort = 8004, gitName, gitEmail, output } = options;

  const stack = loadAndMergeStacks(stackNames);
  const services = loadServices(selectedServices);
  const serviceVolumes = extractServiceVolumes(services);

  const context = { name, repos, multiRepo, stack, services, serviceVolumes, fullInternet, includeCompose, localClaude, ungit, sshPort, firewallPort, ungitPort, gitName, gitEmail };

  const devcontainerDir = join(output, '.devcontainer');
  mkdirSync(devcontainerDir, { recursive: true });

  if (localClaude) {
    mkdirSync(join(output, '.project-claude'), { recursive: true });
  }

  // Render všech šablon
  const files = [
    { template: 'project.yml.ejs', output: join(output, 'project.yml') },
    { template: 'init.sh.ejs', output: join(devcontainerDir, 'init.sh'), executable: true },
    ...(!fullInternet ? [{ template: 'init-firewall.sh.ejs', output: join(devcontainerDir, 'init-firewall.sh'), executable: true }] : []),
    ...(!fullInternet ? [{ template: 'CLAUDE.md.ejs', output: join(devcontainerDir, 'CLAUDE.md') }] : []),
    { template: 'Dockerfile.ejs', output: join(devcontainerDir, 'Dockerfile') },
    { template: 'docker-compose.yml.ejs', output: join(devcontainerDir, 'docker-compose.yml') },
    { template: 'devcontainer.json.ejs', output: join(devcontainerDir, 'devcontainer.json') },
  ];

  for (const file of files) {
    const content = renderTemplate(file.template, context);
    writeFileSync(file.output, content);
    if (file.executable) {
      chmodSync(file.output, 0o755);
    }
  }

  // Statické soubory
  const gitignorePath = join(output, '.gitignore');
  if (!existsSync(gitignorePath)) {
    writeFileSync(gitignorePath, '.env\n');
  }
  const envExamplePath = join(devcontainerDir, '.env.example');
  if (!existsSync(envExamplePath)) {
    writeFileSync(envExamplePath, '# Environment variables for this devcontainer\n# Copy to .env and fill in values:\n#   cp .devcontainer/.env.example .devcontainer/.env\n\n# Git credentials for Claude (read-only) — full credential line\n# GIT_CREDENTIALS_READONLY=https://<user>:<read-only-PAT>@<git-host>\n');
  }
}

/**
 * Vypíše instrukce po vygenerování.
 */
export function printInstructions(name, output, { localClaude = false, sshPort = 2222, ungitPort = 8004, ungit = true, repos = [], multiRepo = false, includeCompose = false } = {}) {
  let claudeInfo = '';
  if (localClaude) {
    claudeInfo = `
6. Projektové Claude nastavení (.claude/CLAUDE.md) jsou v .project-claude/
   složce tohoto devcontainer repa — commitujte je do gitu.
   .claude/ je automaticky přidán do git exclude zákaznického repa.
`;
  }

  let multiRepoInfo = '';
  if (multiRepo && repos.length > 0) {
    const repoList = repos.map(r => `  /workspace/${r.name}/`).join('\n');
    multiRepoInfo = `
Workspace obsahuje ${repos.length} repozitáře:
${repoList}
`;
  }

  let includeComposeWarning = '';
  if (includeCompose && multiRepo) {
    const composePaths = repos.map(r => `    ../../${name}/${r.name}/docker-compose.yml`).join('\n');
    includeComposeWarning = `
⚠ Více repozitářů — docker-compose soubory zákaznických repozitářů
  nebyly automaticky includovány. Zkontrolujte compose soubory v:
${composePaths}
  a ručně upravte .devcontainer/docker-compose.yml pokud potřebujete.
`;
  }

  const jetbrainsStep = localClaude ? '7' : '6';

  console.log(`
=== Devcontainer vygenerován: ${output} ===

1. Vytvořte sdílený Docker volume (jednou za stroj):
   docker volume create claude-shared

2. Otevřete devcontainer ve VS Code:
   cd ${output}
   code .
   → "Reopen in Container"

3. Připojení ke Claude Code:
   tmux attach -t claude

4. Odpojení (Claude dál pracuje):
   Ctrl+B, pak D

5. Nastavení git credentials pro Claude (read-only):
   Na serveru v .devcontainer/.env přidejte:
   GIT_CREDENTIALS_READONLY=https://<user>:<read-only-PAT>@<git-host>
   Pak: docker compose up -d --force-recreate devcontainer
   (Credentials se automaticky seedují při každém startu kontejneru)${ungit ? `

${localClaude ? '7' : '6'}. Git push přes Ungit (write credentials):
   Vytvořte secret soubor na serveru:
   mkdir -p ~/.secrets/${name} && chmod 700 ~/.secrets/${name}
   echo "https://<user>:<write-PAT>@<git-host>" > ~/.secrets/${name}/git-credentials-write
   chmod 600 ~/.secrets/${name}/git-credentials-write
   Pak: docker compose up -d --force-recreate ungit
   Ungit web GUI: http://<hostname>:${ungitPort}` : ''}
${claudeInfo}${multiRepoInfo}${includeComposeWarning}
${jetbrainsStep}. JetBrains IDE (PyCharm, IntelliJ, ...) — přes Gateway:
   - Kontejner exposuje SSH na portu ${sshPort} (mapovaný z kontejneru :22)
   - PyCharm Gateway → SSH na <hostname>:${sshPort}, user: node, bez hesla
   - Backend běží uvnitř kontejneru, otevřete /workspace
   - Interpreter (Python/Node) je přímo v kontejneru, žádná další konfigurace
`);
}
