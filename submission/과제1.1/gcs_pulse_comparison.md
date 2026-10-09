# GCS-PULSE Integration Benchmark: MCP vs. CLI
**Environment:** Codex / Claude Code  
**Service:** GCS-PULSE (Mock Internal Room Booking)  
**Date:** 2026-10-08  
**Author:** DevOps & LLM Benchmarking Simulation

> **Methodology note:** GCS-PULSE is a mock service. Token counts are estimated from
> representative protocol payloads constructed for two canonical operations:
> *Room Lookup* and *Room Booking*. Latency ranges are based on typical
> JSON-RPC vs. subprocess execution profiles. All figures are simulated.

---

## 1. Protocol Payload Samples

### 1a. MCP — Room Lookup

**Tool schema (injected once per session context)**
```json
{
  "name": "gcs_pulse_lookup_rooms",
  "description": "Look up available rooms by date range, capacity, and location",
  "input_schema": {
    "type": "object",
    "properties": {
      "check_in":  { "type": "string", "format": "date" },
      "check_out": { "type": "string", "format": "date" },
      "capacity":  { "type": "integer", "minimum": 1 },
      "location":  { "type": "string" }
    },
    "required": ["check_in", "check_out"]
  }
}
```
*Estimated schema tokens: ~95*

**Tool call (LLM output)**
```json
{
  "type": "tool_use",
  "id": "toolu_01LkR3mXq",
  "name": "gcs_pulse_lookup_rooms",
  "input": {
    "check_in": "2026-10-15",
    "check_out": "2026-10-17",
    "capacity": 2,
    "location": "Seoul HQ"
  }
}
```
*Estimated call tokens: ~65*

**Tool result (injected back as user turn)**
```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01LkR3mXq",
  "content": [{
    "type": "text",
    "text": "{\"rooms\":[{\"id\":\"R-101\",\"name\":\"Standard Room\",\"floor\":1,\"capacity\":2,\"rate_krw\":150000,\"available\":true},{\"id\":\"R-205\",\"name\":\"Deluxe Room\",\"floor\":2,\"capacity\":2,\"rate_krw\":220000,\"available\":true}],\"query_id\":\"q-8821\",\"total\":2}"
  }]
}
```
*Estimated result tokens: ~145*

---

### 1b. CLI — Room Lookup

**Command (LLM output)**
```bash
gcs-pulse rooms \
  --check-in  2026-10-15 \
  --check-out 2026-10-17 \
  --capacity  2 \
  --location  "Seoul HQ"
```
*Estimated command tokens: ~45*

**stdout (injected back)**
```
ROOM ID  NAME           FLOOR  CAP  RATE (KRW)  STATUS
R-101    Standard Room  1      2    150,000     Available
R-205    Deluxe Room    2      2    220,000     Available

2 room(s) found  [query_id: q-8821]
```
*Estimated stdout tokens: ~85*

---

### 1c. MCP — Room Booking

**Tool call**
```json
{
  "type": "tool_use",
  "id": "toolu_02Pm9sNYw",
  "name": "gcs_pulse_book_room",
  "input": {
    "room_id":    "R-101",
    "check_in":   "2026-10-15",
    "check_out":  "2026-10-17",
    "guest_name": "Kim Jisu",
    "purpose":    "팀 오프사이트"
  }
}
```
*Estimated call tokens: ~95*

**Tool result**
```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_02Pm9sNYw",
  "content": [{
    "type": "text",
    "text": "{\"booking_id\":\"BK-20261015-R101\",\"room_id\":\"R-101\",\"guest\":\"Kim Jisu\",\"check_in\":\"2026-10-15\",\"check_out\":\"2026-10-17\",\"nights\":2,\"total_krw\":300000,\"status\":\"CONFIRMED\",\"confirmation_code\":\"GCP-7743\"}"
  }]
}
```
*Estimated result tokens: ~155*

---

### 1d. CLI — Room Booking

**Command**
```bash
gcs-pulse book \
  --room      R-101 \
  --check-in  2026-10-15 \
  --check-out 2026-10-17 \
  --guest     "Kim Jisu" \
  --purpose   "팀 오프사이트"
```
*Estimated command tokens: ~60*

**stdout**
```
✓ Booking confirmed
  ID:     BK-20261015-R101
  Room:   R-101 (Standard Room)
  Guest:  Kim Jisu
  Dates:  2026-10-15 → 2026-10-17 (2 nights)
  Total:  ₩300,000
  Code:   GCP-7743
```
*Estimated stdout tokens: ~75*

---

## 2. Token Benchmark Table

### Per-Operation (single call)

| Operation | Approach | Schema / Overhead | Call (input) | Response (output) | **Total** |
|-----------|----------|:-----------------:|:------------:|:-----------------:|:---------:|
| Room Lookup | **MCP** | 95 | 65 | 145 | **305** |
| Room Lookup | **CLI** | 0 | 45 | 85 | **130** |
| Room Booking | **MCP** | 95 | 95 | 155 | **345** |
| Room Booking | **CLI** | 0 | 60 | 75 | **135** |

> Schema overhead (95 tokens) is a per-session, one-time cost for MCP; it is
> amortized to ~5 tokens per call over a 20-call session.

### Full Session (lookup → confirm → book, amortized schema)

| Session Scenario | MCP Tokens | CLI Tokens | Delta |
|------------------|:----------:|:----------:|:-----:|
| Lookup only | 305 | 130 | +175 (+135%) |
| Lookup + Booking | 650 | 265 | +385 (+145%) |
| 10× Bookings (batch) | 4,050 | 1,350 | +2,700 (+200%) |
| 10× Bookings (amortized schema) | 3,955 | 1,350 | +2,605 (+193%) |

---

## 3. Latency Comparison

| Operation | MCP p50 | MCP p95 | CLI p50 | CLI p95 | Notes |
|-----------|:-------:|:-------:|:-------:|:-------:|-------|
| Room Lookup | 210 ms | 420 ms | 95 ms | 195 ms | MCP adds JSON-RPC envelope + schema validation |
| Room Booking | 260 ms | 510 ms | 110 ms | 220 ms | MCP confirmation round-trip vs. direct stdout |
| Error response | 180 ms | 350 ms | 80 ms | 160 ms | MCP error object vs. stderr line |
| Cold start (first call) | +350 ms | +600 ms | +120 ms | +250 ms | MCP transport handshake; CLI subprocess spawn |

---

## 4. Developer Experience (DX) Analysis

| Dimension | MCP | CLI |
|-----------|-----|-----|
| **Schema discovery** | ✅ Auto-documented via `list_tools()` | ❌ Requires `--help` or reading docs |
| **Type safety** | ✅ JSON Schema validation on input | ❌ Argument parsing errors only at runtime |
| **Structured output** | ✅ JSON always; easy to parse downstream | ⚠️ Text table needs regex/column parsing |
| **Error format** | ✅ Structured `{code, message, data}` | ⚠️ Exit code + unstructured stderr |
| **Multi-step chaining** | ✅ Native in LLM tool-use loop | ⚠️ Manual pipe/script wiring |
| **Debugging** | ⚠️ JSON envelope noise; harder to `curl` manually | ✅ Direct shell replay; easy `--dry-run` |
| **Auth integration** | ⚠️ JWT/token in transport layer (harder to inspect) | ✅ Env vars or `--token` flag, visible in shell |
| **CI/CD pipeline** | ⚠️ Requires MCP runtime in CI container | ✅ Drop-in shell script; no extra deps |
| **Onboarding** | ⚠️ MCP SDK install + server config | ✅ One binary, zero config |

---

## 5. Error Handling & Robustness

### MCP Error Response (structured)
```json
{
  "jsonrpc": "2.0",
  "id": "toolu_03Xr7bQPa",
  "error": {
    "code": -32001,
    "message": "Room R-101 unavailable for requested dates",
    "data": { "room_id": "R-101", "conflict_dates": ["2026-10-16"] }
  }
}
```
**Verdict:** Machine-readable, retry logic trivial, but verbose.

### CLI Error Response (text stderr)
```
Error: Room R-101 unavailable for 2026-10-16
Suggestion: Try R-205 (available, +₩70,000/night)
Exit code: 2
```
**Verdict:** Human-readable, `exit 2` enables shell `||` branching, but LLM must parse natural language to extract the conflict date.

---

## 6. Architectural Pros & Cons

### MCP
**Pros**
- Seamless LLM integration — the model calls tools natively without prompt engineering
- Schema-enforced contracts reduce hallucinated parameters
- Multi-tool composition (lookup → availability check → book) in a single agentic loop
- Observability: every call/result pair is logged in the message stream

**Cons**
- ~2× token overhead vs CLI, increasing cost at scale
- Requires an MCP-compatible runtime and server process (extra infra)
- Cold-start latency penalty; not suitable for high-frequency batch jobs
- Harder to test in isolation without an LLM in the loop

### CLI
**Pros**
- Minimal token overhead — no schema, no JSON-RPC envelope
- Works in any CI/CD pipeline with zero runtime dependencies
- Shell composability: pipe to `jq`, `awk`, cron-schedulable
- Transparent auth via env vars; easy to debug with `--verbose`

**Cons**
- LLM must generate syntactically correct CLI flags (prompt brittleness)
- Unstructured stdout requires fragile parsing for complex responses
- No native retry/error-code contract visible to the model
- Multi-step flows require explicit orchestration in the prompt or a wrapper script

---

## 7. Recommended Team Workflows

| Use Case | Recommended Approach | Rationale |
|----------|----------------------|-----------|
| Interactive LLM-driven booking assistant | **MCP** | Native tool-use loop; schema prevents hallucinated params |
| Nightly batch booking sync / cron job | **CLI** | No LLM overhead; shell-native scheduling |
| CI/CD room availability check | **CLI** | Zero infra deps; exit-code-driven pipeline gating |
| Agentic multi-step itinerary planner | **MCP** | Chained tool calls with shared context |
| Rapid one-off admin lookup | **CLI** | Fastest path; no server required |
| Audit trail / compliance logging | **MCP** | Structured JSON stream is easier to ingest into SIEM |
| Developer onboarding / exploration | **CLI** | Lower barrier; `--help` self-documents |

---

## 8. Summary & Decision Matrix

```
              Token Efficiency   Latency   DX (LLM)   DX (Human)   Infra Cost
MCP           ★★☆☆☆             ★★★☆☆    ★★★★★      ★★★☆☆       ★★☆☆☆
CLI           ★★★★★             ★★★★★    ★★★☆☆      ★★★★★       ★★★★★
```

**Bottom line:**  
Use **MCP** when the primary consumer is an LLM agent making context-sensitive decisions  
(booking assistant, itinerary planner, approval workflow).  
Use **CLI** for everything else — automation, CI, bulk operations, and human-run admin tasks.  
A hybrid pattern (CLI scripts wrapped as MCP tools) gives you both: structured contracts for  
the LLM with shell-level debuggability underneath.
