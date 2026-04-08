#!/usr/bin/env bash
# Integration test: builds firewall Docker image and verifies end-to-end proxy behavior.
# Requires Docker. Intended to run in CI (GitHub Actions), not inside devcontainers.
set -euo pipefail

IMAGE="cc-remote-firewall:integration-test"
CONTAINER="fw-integration-test-$$"
PROXY_PORT=13128
API_PORT=18080
CA_CERT="/tmp/fw-test-ca-$$.pem"

cleanup() {
    echo "[cleanup] Stopping container..."
    docker rm -f "$CONTAINER" 2>/dev/null || true
    rm -f "$CA_CERT"
}
trap cleanup EXIT

echo "=== Building firewall image ==="
docker build -t "$IMAGE" services/firewall/

# LLM credentials from environment (set via GitHub secrets in CI)
LLM_ARGS=()
if [ -n "${AZURE_OPENAI_ENDPOINT:-}" ] && [ -n "${AZURE_OPENAI_API_KEY:-}" ]; then
    echo "=== LLM credentials available — LLM tests will run ==="
    LLM_ARGS=(
        -e "AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}"
        -e "AZURE_OPENAI_API_KEY=${AZURE_OPENAI_API_KEY}"
        -e "AZURE_OPENAI_DEPLOYMENT=${AZURE_OPENAI_DEPLOYMENT:-gpt-5.4-mini}"
        -e "AZURE_OPENAI_API_VERSION=${AZURE_OPENAI_API_VERSION:-2025-12-01-preview}"
        -e "LLM_ENABLED=true"
    )
    HAS_LLM=true
else
    echo "=== No LLM credentials — LLM tests will be skipped ==="
    LLM_ARGS=(-e "LLM_ENABLED=false")
    HAS_LLM=false
fi

echo "=== Starting container ==="
docker run -d --name "$CONTAINER" \
    -p "$PROXY_PORT:3128" \
    -p "$API_PORT:8080" \
    "${LLM_ARGS[@]}" \
    "$IMAGE"

echo "=== Waiting for CA cert + proxy + API ==="
for i in $(seq 1 60); do
    if docker exec "$CONTAINER" test -f /data/certs/mitmproxy-ca-cert.pem 2>/dev/null &&
       docker exec "$CONTAINER" bash -c 'echo > /dev/tcp/localhost/3128' 2>/dev/null &&
       curl -sf "http://localhost:$API_PORT/api/rules" > /dev/null 2>&1; then
        echo "[ready] All services up after ${i}s"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "FAIL: services did not start within 60s"
        docker logs "$CONTAINER"
        exit 1
    fi
    sleep 1
done

docker cp "$CONTAINER:/data/certs/mitmproxy-ca-cert.pem" "$CA_CERT"

PASS=0
FAIL=0

assert_status() {
    local test_name="$1"
    local expected="$2"
    local actual="$3"
    if [ "$actual" = "$expected" ]; then
        echo "  PASS: $test_name (HTTP $actual)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $test_name (expected $expected, got $actual)"
        FAIL=$((FAIL + 1))
    fi
}

# --- Proxy tests ---

echo ""
echo "=== Proxy tests ==="

# Test 1: whitelisted domain passes
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --proxy "http://localhost:$PROXY_PORT" --cacert "$CA_CERT" \
    --max-time 15 \
    "https://pypi.org/" 2>/dev/null || echo "000")
assert_status "whitelisted domain (pypi.org)" "200" "$STATUS"

# Test 2: unknown domain blocked
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --proxy "http://localhost:$PROXY_PORT" --cacert "$CA_CERT" \
    --max-time 10 \
    "https://evil-test-domain.example.com/" 2>/dev/null || echo "000")
assert_status "unknown domain blocked" "403" "$STATUS"

# Test 3: git push blocked (github.com is whitelisted but git-receive-pack is denied)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --proxy "http://localhost:$PROXY_PORT" --cacert "$CA_CERT" \
    --max-time 10 \
    -X POST "https://github.com/user/repo.git/git-receive-pack" 2>/dev/null || echo "000")
assert_status "git push blocked" "403" "$STATUS"

# Test 4: git pull allowed (git-upload-pack is not blocked)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --proxy "http://localhost:$PROXY_PORT" --cacert "$CA_CERT" \
    --max-time 10 \
    "https://github.com/user/repo.git/info/refs?service=git-upload-pack" 2>/dev/null || echo "000")
# GitHub may return 401 (needs auth) but NOT 403 (not blocked by firewall)
if [ "$STATUS" != "403" ] && [ "$STATUS" != "000" ]; then
    echo "  PASS: git pull not blocked (HTTP $STATUS)"
    PASS=$((PASS + 1))
else
    echo "  FAIL: git pull blocked (HTTP $STATUS)"
    FAIL=$((FAIL + 1))
fi

# --- API tests ---

echo ""
echo "=== API tests ==="

# Test 5: dashboard returns HTML
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$API_PORT/")
assert_status "dashboard" "200" "$STATUS"

# Test 6: rules list works
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$API_PORT/api/rules")
assert_status "list rules" "200" "$STATUS"

# Test 7: git-receive-pack block rule exists
RULES=$(curl -s "http://localhost:$API_PORT/api/rules")
if echo "$RULES" | grep -q "git-receive-pack"; then
    echo "  PASS: git-receive-pack block rule present"
    PASS=$((PASS + 1))
else
    echo "  FAIL: git-receive-pack block rule missing"
    FAIL=$((FAIL + 1))
fi

# --- Dynamic rule test ---

echo ""
echo "=== Dynamic rule test ==="

# Test 8: add allow rule, then verify domain passes through proxy
curl -s -X POST "http://localhost:$API_PORT/api/rules" \
    -H "Content-Type: application/json" \
    -d '{"domain":"httpbin.org","action":"allow"}' > /dev/null

# Wait for addon to reload rules (5s interval + margin)
sleep 7

STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --proxy "http://localhost:$PROXY_PORT" --cacert "$CA_CERT" \
    --max-time 15 \
    "https://httpbin.org/get" 2>/dev/null || echo "000")
assert_status "newly allowed domain (httpbin.org)" "200" "$STATUS"

# --- LLM tests (only when credentials available) ---

if [ "$HAS_LLM" = "true" ]; then
    echo ""
    echo "=== LLM evaluation tests ==="

    # Test 9: unknown safe domain auto-approved by LLM
    # docs.python.org is NOT in the default whitelist but is clearly safe
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        --proxy "http://localhost:$PROXY_PORT" --cacert "$CA_CERT" \
        --max-time 15 \
        "https://docs.python.org/3/library/asyncio.html" 2>/dev/null || echo "000")
    assert_status "LLM auto-approve safe domain (docs.python.org)" "200" "$STATUS"

    # Test 10: check that LLM decision was logged
    DECISIONS=$(curl -s "http://localhost:$API_PORT/api/decisions?limit=5")
    if echo "$DECISIONS" | grep -q "docs.python.org"; then
        echo "  PASS: LLM decision logged for docs.python.org"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: LLM decision not found in /api/decisions"
        FAIL=$((FAIL + 1))
    fi

    # Test 11: check pending review exists for auto-approved domain
    PENDING=$(curl -s "http://localhost:$API_PORT/api/decisions/pending-review")
    if echo "$PENDING" | grep -q "docs.python.org"; then
        echo "  PASS: auto-approved domain in pending review"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: auto-approved domain not in pending review"
        FAIL=$((FAIL + 1))
    fi
else
    echo ""
    echo "=== LLM tests skipped (no credentials) ==="
fi

# --- Results ---

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "Container logs:"
    docker logs "$CONTAINER" 2>&1 | tail -30
    exit 1
fi
