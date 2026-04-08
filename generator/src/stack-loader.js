import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import yaml from 'js-yaml';

const __dirname = dirname(fileURLToPath(import.meta.url));
const STACKS_DIR = join(__dirname, 'templates', 'stacks');
const SERVICES_DIR = join(__dirname, 'templates', 'services');

function loadYaml(filePath, label) {
  let content;
  try {
    content = readFileSync(filePath, 'utf-8');
  } catch (err) {
    if (err.code === 'ENOENT') {
      throw new Error(`${label} not found at ${filePath}`);
    }
    throw err;
  }
  return yaml.load(content);
}

/**
 * Načte stack (SDK/runtime) definici z YAML souboru.
 */
export function loadStack(stackName) {
  const stack = loadYaml(join(STACKS_DIR, `${stackName}.yml`), `Stack "${stackName}"`);

  if (!stack.name) throw new Error(`Stack "${stackName}" missing required field: name`);
  if (!stack.base_image) throw new Error(`Stack "${stackName}" missing required field: base_image`);
  if (!stack.tools || !Array.isArray(stack.tools)) {
    throw new Error(`Stack "${stackName}" missing required field: tools (array)`);
  }

  return stack;
}

/**
 * Načte a sloučí více stacků. První stack určuje base_image a name,
 * vscode_extensions a firewall_domains se sloučí ze všech.
 */
export function loadAndMergeStacks(stackNames) {
  const stacks = stackNames.map(s => loadStack(s));
  if (stacks.length === 1) return stacks[0];

  const primary = stacks[0];
  const allExtensions = [...new Set(stacks.flatMap(s => s.vscode_extensions || []))];
  const allDomains = [...new Set(stacks.flatMap(s => s.firewall_domains || []))];

  return {
    ...primary,
    vscode_extensions: allExtensions,
    firewall_domains: allDomains,
  };
}

/**
 * Načte definici služby z YAML souboru.
 */
export function loadService(serviceName) {
  const service = loadYaml(join(SERVICES_DIR, `${serviceName}.yml`), `Service "${serviceName}"`);

  if (!service.name) throw new Error(`Service "${serviceName}" missing required field: name`);
  if (!service.image) throw new Error(`Service "${serviceName}" missing required field: image`);

  return service;
}

/**
 * Načte víc služeb najednou. Vrátí objekt { název: definice }.
 */
export function loadServices(serviceNames = []) {
  const result = {};
  for (const name of serviceNames) {
    const service = loadService(name);
    result[name] = service;
  }
  return result;
}
