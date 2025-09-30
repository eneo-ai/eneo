# Crawler Debugging Guide

## Problem Statement

**urllib works in the container, but Scrapy/Twisted doesn't**

This guide documents all enhanced logging and diagnostics added to identify the root cause.

---

## What Was Added

### 1. Container Environment Diagnostics (NEW)
**File**: `container_diagnostics.py`

**Purpose**: Identify container-specific issues that affect Twisted but not stdlib

**Checks**:
- ✅ **File descriptor limits** - Twisted uses more FDs than urllib, container might have low ulimits
- ✅ **Memory limits** - Check cgroup memory constraints
- ✅ **Network namespace** - Verify container network isolation
- ✅ **DNS resolution methods** - Compare system getaddrinfo vs Twisted's resolver
- ✅ **Twisted reactor compatibility** - Verify reactor can start in container
- ✅ **Connection pooling settings** - TCP keepalive, socket buffers, conntrack limits
- ✅ **Middleware chain verification** - Ensure custom middlewares aren't breaking requests

**What It Detects**:
- Low file descriptor limits (`ulimit -n < 1024`)
- High TIME-WAIT connection count (port exhaustion)
- IPv6-only DNS resolution (causes timeouts if IPv6 not working)
- Twisted/Crochet import failures
- Network namespace issues

---

### 2. urllib vs Scrapy Configuration Comparison (NEW)
**File**: `scrapy_diagnostics.py`

**Purpose**: Directly compare why urllib works but Scrapy doesn't

**Checks**:
1. **robots.txt blocking** - Even though disabled, check if it would block
2. **TLS library differences** - Python ssl vs Twisted OpenSSL versions
3. **User-Agent filtering** - Check if Scrapy UA triggers bot detection

**Critical Output**: When blocking issue found, logs prominent error with explanation

---

### 3. Scrapy Engine Startup Sequence Tracking (NEW)
**File**: `scrapy_diagnostics.py` + `crawl_spider.py`

**Purpose**: Track EXACTLY where Scrapy hangs during startup

**Execution Phases Tracked**:
1. ✅ Spider class loaded
2. ✅ Crawler runner created
3. ✅ Spider instantiated
4. ✅ **Engine started** (CRITICAL - proves Twisted reactor running)
5. ✅ **First request scheduled** (CRITICAL - proves spider generated requests)
6. ✅ **First response received** (CRITICAL - proves network working)
7. ✅ Item scraped

**Signal Handlers**:
- `engine_started` → Confirms Twisted reactor started
- `request_scheduled` → Confirms requests being queued
- `response_received` → Confirms network connectivity
- `spider_idle` → Detects if no requests generated
- `spider_closed` → Final diagnosis with detailed error messages

---

### 4. Enhanced TLS/Certificate Error Detection
**File**: `debug_middleware.py`

**Purpose**: Explain TLS errors in detail for network team

**Specific Detection**:
- **Unknown CA** - Twisted can't find certificate authority
- **Hostname mismatch** - Certificate doesn't match domain
- **Certificate expired** - Self-explanatory
- **Handshake failure** - Protocol/cipher incompatibility

**Output Format**:
```
================================================================================
🔒 TLS/CERTIFICATE ERROR DETECTED
================================================================================
ROOT CAUSE: TLS certificate verification failed

SPECIFIC ISSUE: Unknown Certificate Authority (Okänt CA)

EXPLANATION:
  - Twisted's OpenSSL cannot find the certificate authority that signed this cert
  - Python's ssl module (urllib) uses different CA bundle and DOES trust it
  - This is why urllib works but Scrapy/Twisted doesn't

SOLUTIONS:
  1. Add CA certificate to system trust store in container
  2. Configure Twisted to use same CA bundle as Python ssl
  3. Disable certificate verification (NOT RECOMMENDED for production)

FOR NETWORK TEAM:
  - Check if site uses internal/self-signed certificate
  - Verify certificate chain is complete
  - Compare: openssl s_client -connect {host}:443 -showcerts
```

---

### 5. Scrapy Built-in Debug Mode Enabled
**File**: `crawler.py`

**Changes**:
```python
"LOG_LEVEL": "DEBUG",         # Most verbose Scrapy logging
"LOGSTATS_INTERVAL": 10.0,    # Stats every 10s (was 60s)
"DUPEFILTER_DEBUG": True,     # Log duplicate filtering
"COOKIES_DEBUG": True,        # Log cookie handling
```

**Benefit**: Uses Scrapy's own debugging instead of custom logging

---

### 6. Real-time Progress Monitoring
**File**: `crawler.py`

**Purpose**: Detect if Scrapy is stuck without waiting for timeout

**Every 15 seconds logs**:
- Result file size (bytes written)
- Warns if no output after 60s
- Checks Scrapy stats (if available)
- Escalating warnings at 60s, 90s, 120s intervals

---

### 7. Comprehensive Network Diagnostics (KEPT)
**File**: `network_diagnostics.py`

**Purpose**: Detailed network-level info for infrastructure team

**Provides**:
- TCP connection timing (DNS, connect, TLS, HTTP phases)
- Comparison of curl, wget, urllib, socket methods
- Environment capture (DNS, routing, proxies, MTU, external IP)
- Proxy detection
- MTU path discovery

**Why Kept**: Network/Linux team needs this for infrastructure debugging

---

## Log Access in Podman Environment

### Where Logs Are:

1. **Stdout (podman logs)**
   ```bash
   podman logs <worker_container_id>
   podman logs <worker_container_id> -f   # Follow realtime
   ```

2. **Diagnostic Log File** (inside container)
   ```
   /tmp/crawl_diagnostics_crawl_<timestamp>.log
   ```

3. **Persistent Copy** (if mounted)
   ```
   /workspace/backend/crawler_logs/crawl_diagnostics_<timestamp>.log
   ```

### How to Access:

```bash
# View logs in realtime
podman logs -f <worker_container_id>

# Copy diagnostic file out
podman cp <worker_container_id>:/tmp/crawl_diagnostics_<id>.log ./

# View file directly
podman exec <worker_container_id> cat /tmp/crawl_diagnostics_<id>.log

# List all diagnostic logs
podman exec <worker_container_id> ls -lh /tmp/crawl_diagnostics_*
podman exec <worker_container_id> ls -lh /workspace/backend/crawler_logs/
```

---

## What The Logs Will Tell You

After a failed crawl, the logs will definitively answer:

### Phase 1: Pre-flight (Before Scrapy starts)
- ✅ **Can urllib fetch the URL?** → If no: container networking broken
- ✅ **What are the file descriptor limits?** → If low: increase ulimits
- ✅ **Are there DNS resolution differences?** → IPv6 vs IPv4 issues
- ✅ **Can Twisted/Crochet be imported?** → Missing dependencies
- ✅ **Is robots.txt blocking?** → Should be disabled, but verified
- ✅ **TLS library versions match?** → Python ssl vs Twisted OpenSSL

### Phase 2: Scrapy Engine Startup
- ✅ **Did Scrapy engine start?** → If log shows "ENGINE STARTED", Twisted reactor is working
- ✅ **Were requests scheduled?** → If log shows "First request scheduled", spider generated requests
- ✅ **Did requests reach downloader?** → If `downloader/request_count > 0` in stats

### Phase 3: Network Execution
- ✅ **Were responses received?** → If log shows "First response received", network is working
- ✅ **What HTTP status codes?** → 403/404 = blocking, 200 = working
- ✅ **TLS errors?** → Detailed certificate error analysis

### Phase 4: Final Diagnosis
Spider closed log provides exact diagnosis:
- **0 requests** → Engine problem or start_requests() failed
- **Requests but 0 responses** → Network/DNS/TLS/Firewall issue
- **Responses but 0 items** → Parser problem

---

## Most Likely Root Causes (Based on urllib working)

Since urllib works in the container, we can rule out:
- ❌ Container networking completely broken
- ❌ DNS completely broken
- ❌ Firewall blocking ALL traffic

Most likely causes (in order of probability):

### 1. **Unknown Certificate Authority (Okänt CA)** - MOST LIKELY
**Symptoms**: TLS handshake fails with "unknown ca" or "unable to get local issuer certificate"

**Why**: Swedish municipality sites often use internal CAs. Python's ssl module and Twisted's OpenSSL use different CA bundles.

**Detection**: Look for "TLS/CERTIFICATE ERROR" with "Unknown Certificate Authority"

**Solutions**:
```bash
# Add CA cert to container
podman cp ca-cert.crt <container>:/usr/local/share/ca-certificates/
podman exec <container> update-ca-certificates

# Or in Dockerfile
COPY ca-cert.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates
```

### 2. **Twisted Reactor Startup Failure**
**Symptoms**: No "ENGINE STARTED" log, hangs immediately

**Why**: Crochet/Twisted may fail to start reactor in container environment

**Detection**: Check if "✅ SCRAPY ENGINE STARTED" appears in logs

**Solutions**: Check Twisted/Crochet compatibility, thread issues

### 3. **File Descriptor Limits**
**Symptoms**: Errors after some requests, or immediate failures

**Why**: Twisted needs many FDs for connection pooling

**Detection**: Check "File descriptor limits" in container diagnostics

**Solutions**:
```bash
# Increase ulimit
podman run --ulimit nofile=4096:4096 ...

# Or in docker-compose.yml / podman-compose.yml
ulimits:
  nofile:
    soft: 4096
    hard: 4096
```

### 4. **DNS Resolution Differences**
**Symptoms**: Hangs on first request, or "DNS resolution failed"

**Why**: Twisted might try IPv6 first and timeout if IPv6 broken

**Detection**: Check "DNS RESOLUTION COMPARISON" in logs, look for IPv6-only

**Solutions**: Force IPv4, fix IPv6 routing, or configure DNS properly

### 5. **Connection Pooling Issues**
**Symptoms**: First request works, subsequent requests hang

**Why**: Scrapy maintains connection pools, urllib doesn't

**Detection**: Check TIME-WAIT connection count in container diagnostics

**Solutions**: Adjust TCP keepalive settings, increase conntrack limits

---

## For Network/Linux Team

### Quick Diagnostics to Run:

```bash
# Check container limits
podman exec <container> ulimit -n
podman exec <container> cat /proc/sys/net/ipv4/ip_local_port_range

# Check DNS
podman exec <container> cat /etc/resolv.conf
podman exec <container> nslookup sundsvall.se

# Check TLS
podman exec <container> python3 -c "import ssl; print(ssl.OPENSSL_VERSION)"
podman exec <container> python3 -c "from OpenSSL import SSL; print(SSL.SSLeay_version(SSL.SSLEAY_VERSION))"

# Test urllib (should work)
podman exec <container> python3 -c "import urllib.request; print(urllib.request.urlopen('https://sundsvall.se').getcode())"

# Check connections
podman exec <container> ss -tan | grep -c ESTAB
podman exec <container> ss -tan | grep -c TIME-WAIT

# Check CA certificates
podman exec <container> ls /etc/ssl/certs/ | wc -l
```

### Network Trace:

If needed, capture network traffic:
```bash
# Install tcpdump in container
podman exec <container> apt-get update && apt-get install -y tcpdump

# Capture traffic
podman exec <container> tcpdump -i any -w /tmp/capture.pcap host sundsvall.se

# Copy out
podman cp <container>:/tmp/capture.pcap ./
```

---

## Testing the Enhanced Logging

To verify the logging works, try these test cases:

### Test 1: Known Working Site
```python
# Should show all green checkmarks
url = "https://httpbin.org/html"
```

### Test 2: Known Failing Site
```python
# Should show detailed TLS error if CA issue
url = "https://sundsvall.se"
```

### Test 3: IPv6 Test
```python
# Should show IPv6 vs IPv4 differences
url = "https://ipv6.google.com"
```

---

## Summary: What Changed

| Component | Before | After |
|-----------|--------|-------|
| **Container diagnostics** | ❌ None | ✅ Full environment checks |
| **urllib comparison** | ❌ None | ✅ Direct comparison with Scrapy |
| **Engine startup tracking** | ❌ Silent failures | ✅ Phase-by-phase checkpoints |
| **TLS error detection** | ⚠️ Generic errors | ✅ Detailed explanations + solutions |
| **Scrapy debug mode** | ⚠️ ERROR level | ✅ DEBUG level, stats every 10s |
| **Progress monitoring** | ⚠️ Basic | ✅ Realtime with warnings |
| **Signal handlers** | ❌ None | ✅ Track every execution phase |
| **Final diagnosis** | ⚠️ Generic | ✅ Specific cause + solutions |

---

## Expected Outcome

When you run a crawl on production that fails, the logs will now contain:

1. ✅ **Clear checkpoint**: "✅ SCRAPY ENGINE STARTED" (or absence proves Twisted issue)
2. ✅ **Clear checkpoint**: "✅ First request scheduled" (or absence proves spider issue)
3. ✅ **Clear checkpoint**: "✅ First response received" (or absence proves network issue)
4. ✅ **Container limits**: File descriptors, memory, connections
5. ✅ **TLS analysis**: If TLS error, detailed explanation with solution
6. ✅ **Final diagnosis**: Exact cause with error counts

This will definitively identify whether the issue is:
- Container environment (limits, namespace, DNS)
- Twisted/Crochet (reactor not starting)
- TLS certificates (unknown CA)
- Network filtering (firewall, proxy)
- DNS resolution (IPv6 vs IPv4)
- Connection pooling (port exhaustion)

The logs are designed so both developers AND network/linux teams can diagnose the issue independently.