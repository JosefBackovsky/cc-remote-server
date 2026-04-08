import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { loadStack, loadAndMergeStacks, loadService, loadServices } from '../src/stack-loader.js';

describe('loadStack', () => {
  it('loads nodejs stack', () => {
    const stack = loadStack('nodejs');
    assert.equal(stack.name, 'nodejs');
    assert.equal(stack.base_image, 'node:22');
    assert.ok(Array.isArray(stack.tools));
    assert.ok(stack.tools.includes('git'));
  });

  it('loads python stack', () => {
    const stack = loadStack('python');
    assert.equal(stack.name, 'python');
    assert.equal(stack.base_image, 'python:3.12');
  });

  it('loads dotnet stack', () => {
    const stack = loadStack('dotnet');
    assert.equal(stack.name, 'dotnet');
    assert.ok(stack.base_image.includes('dotnet'));
  });

  it('throws for unknown stack', () => {
    assert.throws(() => loadStack('nonexistent-stack'), /not found/);
  });
});

describe('loadAndMergeStacks', () => {
  it('single stack returns unchanged', () => {
    const stack = loadAndMergeStacks(['nodejs']);
    assert.equal(stack.name, 'nodejs');
    assert.equal(stack.base_image, 'node:22');
  });

  it('multi-stack uses first base image', () => {
    const stack = loadAndMergeStacks(['python', 'nodejs']);
    assert.equal(stack.name, 'python');
    assert.equal(stack.base_image, 'python:3.12');
  });

  it('multi-stack merges vscode extensions', () => {
    const stack = loadAndMergeStacks(['python', 'nodejs']);
    assert.ok(stack.vscode_extensions.includes('ms-python.python'));
    assert.ok(stack.vscode_extensions.includes('orta.vscode-jest'));
  });

  it('multi-stack deduplicates extensions', () => {
    const stack = loadAndMergeStacks(['nodejs', 'nodejs']);
    const unique = [...new Set(stack.vscode_extensions)];
    assert.equal(stack.vscode_extensions.length, unique.length);
  });
});

describe('loadService', () => {
  it('loads postgres service', () => {
    const svc = loadService('postgres');
    assert.equal(svc.name, 'postgres');
    assert.equal(svc.image, 'postgres:17');
    assert.ok(svc.env.POSTGRES_USER);
  });

  it('loads mongo service', () => {
    const svc = loadService('mongo');
    assert.equal(svc.name, 'mongo');
    assert.ok(svc.image.includes('mongo'));
  });

  it('loads redis service', () => {
    const svc = loadService('redis');
    assert.equal(svc.name, 'redis');
    assert.equal(svc.image, 'redis:7');
  });

  it('loads azurite service', () => {
    const svc = loadService('azurite');
    assert.equal(svc.name, 'azurite');
    assert.ok(svc.image.includes('azurite'));
  });

  it('throws for unknown service', () => {
    assert.throws(() => loadService('nonexistent'), /not found/);
  });
});

describe('loadServices', () => {
  it('loads multiple services', () => {
    const result = loadServices(['postgres', 'redis']);
    assert.ok(result.postgres);
    assert.ok(result.redis);
    assert.equal(Object.keys(result).length, 2);
  });

  it('returns empty object for no services', () => {
    const result = loadServices([]);
    assert.deepEqual(result, {});
  });
});
