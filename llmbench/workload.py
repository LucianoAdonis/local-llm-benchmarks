"""Deterministic benchmark workloads.

Three corpus kinds feed the context-depth scenarios:

* ``diverse``     seeded synthetic multi-language repository (default). Every run gets
                  different text, so neither prefix caches nor chunk-level caches can
                  reuse earlier work, and content-dependent engines (MoE expert caches,
                  lookup tables, drafting) see varied tokens.
* ``repetitive``  the v1 workload: one 10-line Python class repeated with a changing
                  index. Kept to reproduce the 2026-11-23 results and to measure how much
                  a runtime speeds up on repeated content.
* ``file:PATH``   your own text or code. Only its hash and size are stored in results.

Text is produced by a tiny SplitMix64 generator rather than ``random`` so the bytes are
identical on every OS and Python version. ``tests/test_workload.py`` pins a golden hash.
"""
from __future__ import annotations

import hashlib
import os
import zlib
from typing import Dict, List, Optional, Sequence, Tuple

MASK64 = (1 << 64) - 1


class Rng:
    """SplitMix64. Deterministic everywhere; not for cryptography."""

    def __init__(self, seed: int) -> None:
        self.state = seed & MASK64

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        return self.next() % n

    def between(self, low: int, high: int) -> int:
        """Inclusive range."""
        return low + self.below(high - low + 1)

    def pick(self, seq: Sequence):
        return seq[self.below(len(seq))]

    def chance(self, percent: int) -> bool:
        return self.below(100) < percent

    def sample(self, seq: Sequence, count: int) -> List:
        pool = list(seq)
        count = min(count, len(pool))
        for i in range(count):
            j = i + self.below(len(pool) - i)
            pool[i], pool[j] = pool[j], pool[i]
        return pool[:count]


def seed_from(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


# --------------------------------------------------------------------------- vocabulary

NOUNS = (
    "account adapter alert archive artifact asset audit backlog badge balance batch beacon "
    "billing binding blob bucket buffer bundle cache calendar campaign carrier catalog channel "
    "checkpoint cipher claim cluster codec comment commit consumer contract coupon credential "
    "cursor dashboard dataset deadline delivery deployment device digest dispatcher document "
    "domain draft endpoint envelope event exporter feature feed filter fixture fleet folder "
    "gateway grant handler heartbeat hook identity importer incident index inventory invoice "
    "job journal kernel label ledger lease license listener locale lock manifest mapper member "
    "message metric migration mirror module monitor namespace node notice offer order "
    "organization outbox packet parcel partition payload payment permission pipeline plan "
    "policy pool portal preview profile project prompt proxy quota queue receipt record region "
    "registry release replica report request reservation resolver resource review role route "
    "rule sample schedule schema scope secret segment sensor session shard shipment signal "
    "snapshot socket source stage stream subscription summary tenant ticket timeline token "
    "topic trace transfer trigger upload usage vault vendor version volume voucher wallet "
    "warehouse webhook widget window worker workflow workspace zone"
).split()

VERBS = (
    "acquire allocate append apply archive assemble assign attach audit backfill balance batch "
    "broadcast build cancel capture check claim clean collect commit compact compare compile "
    "compress compute configure consume convert copy count decode defer deliver detect dispatch "
    "drain emit encode enqueue estimate evict expand export fetch filter flush forward hydrate "
    "import index inspect invalidate load lock merge migrate normalize notify parse patch "
    "persist plan prune publish purge queue rank rebuild reconcile record refresh register "
    "release render replay resolve restore retry revoke rotate route sample scan schedule seal "
    "serialize settle shard sign split stage summarize sync throttle track transform trim "
    "unpack update upload validate verify watch"
).split()

ADJS = (
    "active async atomic cached canonical cold compact concurrent critical deferred dirty "
    "durable eager elastic empty encrypted exact expired external fallback final fragile fresh "
    "global hidden hot idle immutable inbound internal lazy legacy local locked manual nested "
    "optional orphaned outbound partial pending primary private public quiet remote robust "
    "secondary shared shallow signed sparse stale static strict tentative transient trusted "
    "unique verbose volatile warm weighted"
).split()

DOMAINS = (
    "analytics auth billing catalog gateway identity ingest inventory notifications orders "
    "payments reporting scheduling search shipping storage"
).split()

UNITS = "second minute hour request batch tenant".split()
SUFFIXES = "Service Manager Store Client Worker Policy Registry Planner Router Reader".split()
PY_TYPES = "int str bool float bytes dict list Optional[str] Optional[int] datetime Decimal".split()
TS_TYPES = "string number boolean Date string[] number[] Record<string,string> unknown".split()
GO_TYPES = "string int64 bool float64 []byte time.Time time.Duration map[string]string".split()
RS_TYPES = "String u64 i64 bool f64 Vec<u8> Option<String> Duration DateTime<Utc>".split()
SQL_TYPES = "TEXT BIGINT INTEGER BOOLEAN NUMERIC(12,2) JSONB TIMESTAMPTZ UUID SMALLINT".split()
ERRORS = "TimeoutError ValueError KeyError RuntimeError PermissionError LookupError ConflictError".split()
LEVELS = "INFO WARN ERROR DEBUG".split()
PY_IMPORTS = (
    "import asyncio",
    "import dataclasses",
    "import functools",
    "import hashlib",
    "import itertools",
    "import json",
    "import logging",
    "import time",
    "from collections import defaultdict, deque",
    "from datetime import datetime, timedelta, timezone",
    "from decimal import Decimal",
    "from typing import Any, Dict, Iterable, List, Optional",
)

SENTENCES = (
    "This module is responsible for the {adj} {noun} and how we {verb} it across each {noun2}.",
    "Callers should {verb} the {noun} only after the {adj} {noun2} check passes.",
    "When the {noun} is {adj}, we {verb} the {noun2} and retry up to {n} times.",
    "A {adj} {noun} can {verb} at most {n} {noun2} entries per {unit}.",
    "Do not {verb} the {noun} while another {noun2} holds the {adj} lock.",
    "If the {noun2} does not respond within {n} {unit}s, {verb} the {noun} and report the {adj} error.",
    "We keep the {adj} {noun} in memory because every {noun2} has to {verb} it on startup.",
    "Known issue: the {noun} may {verb} twice when the {adj} {noun2} restarts.",
    "The {noun} owner decides whether to {verb} or {verb2} the {adj} {noun2}.",
    "Historically this used one {adj} {noun}; the current design can {verb} each {noun2} independently.",
    "Operators can {verb} the {noun} from the {adj} {noun2} console without a deploy.",
    "Each {noun} carries the {adj} {noun2} id so that we can {verb} it later.",
    "Performance note: try to {verb} the {adj} {noun} in batches of {n} to protect the {noun2}.",
    "Security note: never {verb} the {noun} when it came from the {adj} {noun2}.",
    "TODO: {verb} the {adj} {noun} once the {noun2} migration is complete.",
    "See the {noun} runbook before you {verb} anything in the {adj} {noun2}.",
)

CHAT_TOPICS = (
    "how a hash map handles collisions",
    "binary search and its off-by-one traps",
    "database indexes and when they hurt writes",
    "optimistic versus pessimistic locking",
    "how TCP congestion control reacts to packet loss",
    "garbage collection pauses in managed runtimes",
    "event sourcing compared with storing current state",
    "idempotency keys in payment APIs",
    "backpressure in streaming pipelines",
    "consistent hashing for cache clusters",
    "the difference between threads and async tasks",
    "how public-key signatures prove authorship",
    "blue-green versus canary deployments",
    "why floating point sums drift",
    "write-ahead logging in databases",
    "rate limiting with a token bucket",
    "how a bloom filter trades memory for false positives",
    "dependency injection and when it is overkill",
    "the N+1 query problem in ORMs",
    "circuit breakers in service-to-service calls",
    "how DNS resolution and caching work",
    "copy-on-write data structures",
    "schema migrations without downtime",
    "memoization and cache invalidation",
)

FOLLOWUP_FOCUS = (
    "error handling and retries",
    "concurrency and locking",
    "input validation",
    "resource cleanup and timeouts",
    "database access patterns",
    "configuration and deployment risks",
    "logging and observability gaps",
    "naming and API consistency",
)


def _snake(*words: str) -> str:
    return "_".join(words)


def _camel(*words: str) -> str:
    return words[0] + "".join(w.capitalize() for w in words[1:])


def _pascal(*words: str) -> str:
    return "".join(w.capitalize() for w in words)


def _sentence(rng: Rng) -> str:
    return rng.pick(SENTENCES).format(
        adj=rng.pick(ADJS),
        noun=rng.pick(NOUNS),
        noun2=rng.pick(NOUNS),
        verb=rng.pick(VERBS),
        verb2=rng.pick(VERBS),
        n=rng.pick((2, 3, 5, 8, 10, 15, 30, 50, 100, 250, 500)),
        unit=rng.pick(UNITS),
    )


def _paragraph(rng: Rng, low: int = 2, high: int = 4) -> str:
    return " ".join(_sentence(rng) for _ in range(rng.between(low, high)))


# ------------------------------------------------------------------- section generators


def _py_method(rng: Rng, noun: str) -> List[str]:
    verb, other = rng.pick(VERBS), rng.pick(NOUNS)
    arg, item = rng.pick(NOUNS), rng.pick(NOUNS)
    lines = [
        "    %sdef %s(self, %s: %s, *, limit: int = %d) -> %s:"
        % ("async " if rng.chance(25) else "", _snake(verb, noun), arg, rng.pick(PY_TYPES), rng.between(5, 500), rng.pick(PY_TYPES)),
    ]
    if rng.chance(60):
        lines.append('        """%s"""' % _sentence(rng))
    for _ in range(rng.between(3, 6)):
        kind = rng.below(8)
        if kind == 0:
            lines.append("        %s = self.%s.%s(%s, timeout=%d)" % (other, rng.pick(NOUNS), _snake(rng.pick(VERBS), rng.pick(NOUNS)), arg, rng.between(1, 90)))
        elif kind == 1:
            lines += [
                "        if not %s or %s.%s is None:" % (arg, arg, rng.pick(NOUNS)),
                '            raise %s("%s %s is %s")' % (rng.pick(ERRORS), noun, rng.pick(NOUNS), rng.pick(ADJS)),
            ]
        elif kind == 2:
            lines += [
                "        for %s in %s[:limit]:" % (item, other),
                "            self._%s.append(%s(%s, %s=%d))" % (rng.pick(NOUNS), _snake(rng.pick(VERBS), item), item, rng.pick(NOUNS), rng.between(0, 64)),
            ]
        elif kind == 3:
            lines += [
                "        try:",
                "            %s = %s(%s)" % (item, _snake(rng.pick(VERBS), rng.pick(NOUNS)), arg),
                "        except %s as exc:" % rng.pick(ERRORS),
                '            log.warning("%s failed for %%s: %%s", %s, exc)' % (_snake(verb, noun), arg),
                "            return %s" % rng.pick(("None", "[]", "{}", "False", "0")),
            ]
        elif kind == 4:
            lines.append(
                "        %s = [%s.%s for %s in %s if %s.%s %s %d]"
                % (rng.pick(NOUNS), item, rng.pick(NOUNS), item, other, item, rng.pick(NOUNS), rng.pick((">", "<", ">=", "!=", "==")), rng.between(0, 900))
            )
        elif kind == 5:
            lines += [
                "        with self._%s_lock:" % rng.pick(NOUNS),
                "            self._%s[%s] = time.monotonic() + %d" % (rng.pick(NOUNS), arg, rng.between(1, 3600)),
            ]
        elif kind == 6:
            lines.append('        metrics.counter("%s.%s.%s").inc(%d)' % (rng.pick(DOMAINS), noun, rng.pick(VERBS), rng.between(1, 9)))
        else:
            lines.append("        # %s" % _sentence(rng))
    lines.append("        return %s" % rng.pick((other, "self._%s" % rng.pick(NOUNS), "len(%s)" % other, "bool(%s)" % arg)))
    lines.append("")
    return lines


def _gen_python(rng: Rng) -> Tuple[str, str]:
    noun = rng.pick(NOUNS)
    path = "services/%s/%s_%s.py" % (rng.pick(DOMAINS), noun, rng.pick(VERBS))
    out = ['"""%s"""' % _paragraph(rng, 1, 2), "from __future__ import annotations", ""]
    out += sorted(rng.sample(PY_IMPORTS, rng.between(2, 5)))
    out += [
        "",
        "log = logging.getLogger(__name__)",
        "%s = %d" % (_snake("max", noun, rng.pick(NOUNS)).upper(), rng.between(8, 4096)),
        "%s = %d" % (_snake(rng.pick(ADJS), "timeout", "s").upper(), rng.between(1, 120)),
        "",
        "",
        "class %s:" % _pascal(rng.pick(ADJS), noun, rng.pick(SUFFIXES)),
        '    """%s"""' % _sentence(rng),
        "",
    ]
    for _ in range(rng.between(2, 4)):
        out += _py_method(rng, noun)
    return path, "\n".join(out)


def _gen_typescript(rng: Rng) -> Tuple[str, str]:
    noun, dom = rng.pick(NOUNS), rng.pick(DOMAINS)
    name = _pascal(rng.pick(ADJS), noun)
    path = "web/src/%s/%s.ts" % (dom, _camel(rng.pick(VERBS), noun))
    out = [
        "// %s" % _sentence(rng),
        'import { http } from "../lib/http";',
        'import type { %s } from "../types/%s";' % (_pascal(rng.pick(NOUNS)), rng.pick(NOUNS)),
        "",
        "export interface %s {" % name,
        "  id: string;",
    ]
    fields = rng.sample(NOUNS, rng.between(3, 6))
    for field in fields:
        out.append("  %s%s: %s;" % (_camel(field, rng.pick(NOUNS)), "?" if rng.chance(30) else "", rng.pick(TS_TYPES)))
    out += ["}", ""]
    for _ in range(rng.between(1, 3)):
        fn, arg = _camel(rng.pick(VERBS), noun, rng.pick(NOUNS)), rng.pick(NOUNS)
        out += [
            "export async function %s(%s: %s, opts: { signal?: AbortSignal; retries?: number } = {}): Promise<%s[]> {" % (fn, arg, rng.pick(TS_TYPES), name),
            "  const res = await http.get(`/api/v%d/%s/%ss`, { params: { %s, limit: %d }, signal: opts.signal });" % (rng.between(1, 4), dom, noun, arg, rng.between(10, 500)),
            "  if (!res.ok) {",
            "    throw new Error(`%s %s failed: ${res.status}`);" % (rng.pick(VERBS), noun),
            "  }",
            "  const items = (await res.json()) as %s[];" % name,
            "  return items",
            "    .filter((item) => item.%s !== %s)" % (_camel(rng.pick(fields), rng.pick(NOUNS)), rng.pick(("undefined", "null", '""', "0", "false"))),
            "    .slice(0, opts.retries ?? %d);" % rng.between(1, 50),
            "}",
            "",
        ]
    return path, "\n".join(out)


def _gen_go(rng: Rng) -> Tuple[str, str]:
    noun, dom = rng.pick(NOUNS), rng.pick(DOMAINS)
    name = _pascal(rng.pick(ADJS), noun)
    path = "internal/%s/%s_%s.go" % (dom, noun, rng.pick(VERBS))
    out = ["package %s" % dom, "", "// %s %s" % (name, _sentence(rng)), "type %s struct {" % name, "\tID string"]
    for field in rng.sample(NOUNS, rng.between(2, 5)):
        out.append("\t%s %s" % (_pascal(field), rng.pick(GO_TYPES)))
    out += ["}", ""]
    for _ in range(rng.between(1, 3)):
        verb, table = rng.pick(VERBS), _snake(dom, rng.pick(NOUNS))
        out += [
            "func (s *%sStore) %s%s(ctx context.Context, id string) (*%s, error) {" % (name, _pascal(verb), _pascal(noun), name),
            '\trow := s.db.QueryRowContext(ctx, "SELECT id, %s FROM %s WHERE id = $1 AND %s > $2", id, %d)' % (rng.pick(NOUNS), table, rng.pick(NOUNS), rng.between(0, 1000)),
            "\tvar out %s" % name,
            "\tif err := row.Scan(&out.ID); err != nil {",
            '\t\treturn nil, fmt.Errorf("%s %s %%q: %%w", id, err)' % (verb, noun),
            "\t}",
            "\tif time.Since(out.%s) > %d*time.%s {" % (_pascal(rng.pick(NOUNS)), rng.between(1, 90), rng.pick(("Second", "Minute", "Hour"))),
            "\t\ts.metrics.%s.Inc()" % _pascal(rng.pick(ADJS), rng.pick(NOUNS)),
            "\t}",
            "\treturn &out, nil",
            "}",
            "",
        ]
    return path, "\n".join(out)


def _gen_rust(rng: Rng) -> Tuple[str, str]:
    noun, dom = rng.pick(NOUNS), rng.pick(DOMAINS)
    name, err = _pascal(rng.pick(ADJS), noun), _pascal(noun, "Error")
    path = "crates/%s/src/%s.rs" % (dom, noun)
    states = [_pascal(s) for s in rng.sample(ADJS, 3)]
    out = [
        "//! %s" % _sentence(rng),
        "#[derive(Debug, Clone, Serialize, Deserialize)]",
        "pub struct %s {" % name,
        "    pub id: Uuid,",
        "    pub state: %sState," % name,
    ]
    for field in rng.sample(NOUNS, rng.between(2, 4)):
        out.append("    pub %s: %s," % (field, rng.pick(RS_TYPES)))
    out += ["}", "", "impl %s {" % name]
    for _ in range(rng.between(1, 2)):
        verb, arg = rng.pick(VERBS), rng.pick(NOUNS)
        out += [
            "    pub fn %s(&mut self, %s: %s) -> Result<(), %s> {" % (_snake(verb, rng.pick(NOUNS)), arg, rng.pick(RS_TYPES), err),
            "        match self.state {",
            "            %sState::%s => self.state = %sState::%s," % (name, states[0], name, states[1]),
            "            %sState::%s if self.%s > %d => return Err(%s::%s)," % (name, states[1], rng.pick(NOUNS), rng.between(1, 512), err, _pascal(rng.pick(ADJS))),
            "            _ => tracing::debug!(%s = ?%s, \"%s skipped\")," % (arg, arg, verb),
            "        }",
            "        Ok(())",
            "    }",
            "",
        ]
    out.append("}")
    return path, "\n".join(out)


def _gen_sql(rng: Rng) -> Tuple[str, str]:
    noun, dom = rng.pick(NOUNS), rng.pick(DOMAINS)
    table, other = "%s_%ss" % (dom, noun), "%s_%ss" % (dom, rng.pick(NOUNS))
    path = "db/migrations/%04d_%s_%s.sql" % (rng.between(1, 9999), rng.pick(VERBS), noun)
    cols = rng.sample(NOUNS, rng.between(3, 7))
    out = ["-- %s" % _sentence(rng), "CREATE TABLE %s (" % table, "    id BIGSERIAL PRIMARY KEY,"]
    for col in cols:
        out.append("    %s %s%s," % (col, rng.pick(SQL_TYPES), " NOT NULL" if rng.chance(60) else ""))
    out += [
        "    created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        ");",
        "CREATE INDEX idx_%s_%s ON %s (%s, %s);" % (table, cols[0], table, cols[0], cols[1]),
        "",
        "SELECT a.id, a.%s, count(b.id) AS %s_count" % (cols[0], rng.pick(NOUNS)),
        "FROM %s a LEFT JOIN %s b ON b.%s_id = a.id" % (table, other, noun),
        "WHERE a.%s > %d AND a.%s = '%s'" % (cols[1], rng.between(0, 10000), cols[2], rng.pick(ADJS)),
        "GROUP BY a.id, a.%s HAVING count(b.id) > %d" % (cols[0], rng.between(1, 50)),
        "ORDER BY a.created_at DESC LIMIT %d;" % rng.between(10, 1000),
    ]
    return path, "\n".join(out)


def _gen_yaml(rng: Rng) -> Tuple[str, str]:
    noun, dom = rng.pick(NOUNS), rng.pick(DOMAINS)
    path = "deploy/%s/%s-%s.yaml" % (dom, noun, rng.pick(VERBS))
    out = [
        "# %s" % _sentence(rng),
        "service:",
        "  name: %s-%s" % (dom, noun),
        "  replicas: %d" % rng.between(1, 24),
        "  resources:",
        '    cpu: "%dm"' % (rng.between(1, 80) * 50),
        '    memory: "%dMi"' % (rng.between(1, 64) * 128),
        "  env:",
    ]
    for _ in range(rng.between(3, 7)):
        out += [
            "    - name: %s" % _snake(rng.pick(ADJS), rng.pick(NOUNS), rng.pick(NOUNS)).upper(),
            '      value: "%s"' % rng.pick((str(rng.between(1, 9000)), rng.pick(ADJS), "%ds" % rng.between(1, 600), "https://%s.internal.test/%s" % (rng.pick(DOMAINS), rng.pick(NOUNS)))),
        ]
    out += ["  alerts:"]
    for _ in range(rng.between(1, 3)):
        out += [
            "    - metric: %s.%s.%s" % (dom, rng.pick(NOUNS), rng.pick(VERBS)),
            "      threshold: %d" % rng.between(1, 5000),
            "      for: %dm" % rng.between(1, 60),
        ]
    return path, "\n".join(out)


def _gen_markdown(rng: Rng) -> Tuple[str, str]:
    noun = rng.pick(NOUNS)
    path = "docs/%s/%s-%s.md" % (rng.pick(DOMAINS), rng.pick(ADJS), noun)
    out = ["# %s %s %s" % (rng.pick(VERBS).capitalize(), rng.pick(ADJS), noun), "", _paragraph(rng, 3, 5), "", "## %s" % _pascal(rng.pick(NOUNS)), ""]
    for _ in range(rng.between(3, 6)):
        out.append("- %s" % _sentence(rng))
    out += ["", _paragraph(rng, 2, 4)]
    return path, "\n".join(out)


def _gen_json(rng: Rng) -> Tuple[str, str]:
    noun = rng.pick(NOUNS)
    path = "fixtures/%s/%s_%04d.json" % (rng.pick(DOMAINS), noun, rng.between(1, 9999))
    out = ["{", '  "id": "%s-%06d",' % (noun, rng.between(1, 999999)), '  "state": "%s",' % rng.pick(ADJS), '  "%ss": [' % rng.pick(NOUNS)]
    count = rng.between(2, 5)
    for i in range(count):
        out.append(
            '    {"%s": "%s", "%s": %d, "%s": %s}%s'
            % (rng.pick(NOUNS), rng.pick(ADJS), rng.pick(NOUNS), rng.between(0, 99999), rng.pick(NOUNS), rng.pick(("true", "false", "null")), "," if i < count - 1 else "")
        )
    out += ["  ],", '  "note": "%s"' % _sentence(rng), "}"]
    return path, "\n".join(out)


def _gen_shell(rng: Rng) -> Tuple[str, str]:
    noun, dom = rng.pick(NOUNS), rng.pick(DOMAINS)
    path = "scripts/%s_%s.sh" % (rng.pick(VERBS), noun)
    out = ["#!/usr/bin/env bash", "# %s" % _sentence(rng), "set -euo pipefail", ""]
    out += [
        '%s="${1:-%s}"' % (noun.upper(), rng.pick(ADJS)),
        'for %s in $(seq 1 %d); do' % (rng.pick(NOUNS), rng.between(2, 40)),
        '  curl -fsS --max-time %d "https://%s.internal.test/%s/${%s}" || { echo "%s %s failed" >&2; exit %d; }' % (rng.between(2, 60), dom, rng.pick(NOUNS), noun.upper(), rng.pick(VERBS), noun, rng.between(1, 9)),
        "  sleep %d" % rng.between(1, 30),
        "done",
        'echo "%s"' % _sentence(rng),
    ]
    return path, "\n".join(out)


def _gen_log(rng: Rng) -> Tuple[str, str]:
    dom = rng.pick(DOMAINS)
    path = "logs/%s/%s-%02d.log" % (dom, rng.pick(NOUNS), rng.between(1, 31))
    out = []
    for _ in range(rng.between(5, 11)):
        out.append(
            "2026-%02d-%02dT%02d:%02d:%02dZ %s %s.%s %s_id=%06d latency_ms=%d %s"
            % (rng.between(1, 12), rng.between(1, 28), rng.below(24), rng.below(60), rng.below(60), rng.pick(LEVELS), dom, rng.pick(NOUNS), rng.pick(NOUNS), rng.between(1, 999999), rng.between(1, 30000), _sentence(rng))
        )
    return path, "\n".join(out)


# (generator, weight). Weights sum to 100.
_GENERATORS = (
    (_gen_python, 22),
    (_gen_typescript, 16),
    (_gen_markdown, 12),
    (_gen_go, 10),
    (_gen_sql, 10),
    (_gen_rust, 8),
    (_gen_yaml, 8),
    (_gen_json, 6),
    (_gen_shell, 4),
    (_gen_log, 4),
)


_MIX_PHASE_CHARS = 6000


class Mixer:
    """Chooses what kind of section comes next so every prompt holds the same mix of text.

    Tokenizers turn log lines into far more tokens per character than prose (2.6 against
    4.9 characters per token in one check). When section kinds were drawn at random, two
    prompts of the same length differed by 10% in tokens, which is more than the room a 4K
    window leaves. Here the kind furthest behind its share of the characters goes next, so
    the mix holds for any prompt size; only the starting point differs from run to run.
    """

    def __init__(self, rng: Rng) -> None:
        self.rng = rng
        self.written = [weight / 100.0 * _MIX_PHASE_CHARS * rng.below(1000) / 1000.0 for _, weight in _GENERATORS]
        self.total = sum(self.written)

    def section(self) -> str:
        behind = [weight / 100.0 * self.total - done for (_, weight), done in zip(_GENERATORS, self.written)]
        index = max(range(len(behind)), key=lambda i: behind[i])
        path, body = _GENERATORS[index][0](self.rng)
        text = "# %s\n%s\n" % (path, body)
        self.written[index] += len(text)
        self.total += len(text)
        return text


def diverse_section(rng: Rng) -> str:
    """One section of a random kind (kept for callers that want a single sample)."""
    roll, total = rng.below(100), 0
    for generator, weight in _GENERATORS:
        total += weight
        if roll < total:
            path, body = generator(rng)
            return "# %s\n%s\n" % (path, body)
    raise AssertionError("generator weights must sum to 100")


def repetitive_section(tag: str, index: int) -> str:
    """The v1 section template (scripts/strata_engine_log_coding_benchmark.py)."""
    name = "w%s_%04d" % (tag, index)
    return (
        "# src/run_%s/workers/worker_%s.py\n"
        "class Worker_%s:\n"
        "    def handle(self, request, store, cache, queue):\n"
        "        request_id = request.headers.get('x-request-id') or make_id()\n"
        "        record = store.load(request.project_id, request.item_id)\n"
        "        if record is None: return error(404, request_id)\n"
        "        if cache.contains(record.version): return cache.get(record.version)\n"
        "        result = queue.submit(self.execute, record, request_id)\n"
        "        store.save_status(request_id, 'running')\n"
        "        return result\n" % (tag, name, name)
    )


# ------------------------------------------------------------------------ file corpora

_TEXT_EXTENSIONS = {
    ".c", ".cc", ".cfg", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html", ".ini", ".java",
    ".js", ".json", ".jsx", ".kt", ".lua", ".md", ".php", ".py", ".rb", ".rs", ".rst", ".scala",
    ".sh", ".sql", ".swift", ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".idea", ".vscode"}
_MAX_FILE_BYTES = 4_000_000
_MAX_CORPUS_BYTES = 64_000_000
_FILE_CHUNK_CHARS = 1800


def load_file_corpus(path: str) -> List[Tuple[str, str]]:
    """Return [(relative_path, text)] in a stable order. Never stores absolute paths."""
    if not str(path).strip():
        raise ValueError("--corpus file: needs a path after the colon")
    root = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(root):
        raise ValueError("corpus path does not exist")
    files: List[Tuple[str, str]] = []
    loaded = 0
    if os.path.isfile(root):
        candidates = [(os.path.basename(root), root)]
    else:
        candidates = []
        for folder, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
            for name in sorted(names):
                full = os.path.join(folder, name)
                if os.path.splitext(name)[1].lower() in _TEXT_EXTENSIONS:
                    candidates.append((os.path.relpath(full, root).replace(os.sep, "/"), full))
    for rel, full in candidates:
        try:
            if os.path.getsize(full) > _MAX_FILE_BYTES:
                continue
            with open(full, "r", encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            continue
        if text.strip():
            files.append((rel, text.replace("\r\n", "\n")))
            loaded += len(text)
            if loaded > _MAX_CORPUS_BYTES:
                break
    if not files:
        raise ValueError("no readable text files found in the corpus path (UTF-8 files with a source or text extension, up to %d MB each)" % (_MAX_FILE_BYTES // 1_000_000))
    return files


# ----------------------------------------------------------------------- corpus builder


class Corpus:
    """Builds context text of a requested size for one run."""

    def __init__(self, spec: str = "diverse") -> None:
        self.files: Optional[List[Tuple[str, str]]] = None
        if spec.startswith("file:"):
            self.kind = "file"
            self.files = load_file_corpus(spec[5:])
            joined = "\n".join("%s\n%s" % item for item in self.files)
            self.file_sha256 = hashlib.sha256(joined.encode("utf-8")).hexdigest()
            self.file_chars = len(joined)
            # Identify a private corpus by content hash, never by its location on disk.
            self.key = "file:" + self.file_sha256[:12]
        elif spec in ("diverse", "repetitive"):
            self.kind = spec
            self.key = spec
        else:
            raise ValueError("corpus must be 'diverse', 'repetitive' or 'file:PATH'")

    def _file_sections(self, rng: Rng):
        """Yield chunks of the user's files in turn, so every prompt samples all of them.

        One file after another made a prompt's token count depend on which file it landed
        in (a lock file of hashes against prose differ three-fold). Taking a slice of each
        file in rotation keeps the mix, and so the tokens per character, steady.
        """
        assert self.files is not None
        order = list(range(len(self.files)))
        first = rng.below(len(order))
        order = order[first:] + order[:first]
        cursors = {}
        for index in order:
            text = self.files[index][1]
            at = text.find("\n", rng.below(len(text))) + 1  # start on a line
            cursors[index] = at if 0 < at < len(text) else 0
        while True:
            for index in order:
                rel, text = self.files[index]
                at = cursors[index]
                end = min(len(text), at + _FILE_CHUNK_CHARS)
                line_end = text.rfind("\n", at, end)
                if end < len(text) and line_end > at:
                    end = line_end + 1
                cursors[index] = 0 if end >= len(text) else end
                yield "# %s\n%s\n" % (rel, text[at:end].rstrip("\n"))

    def build(self, target_chars: int, seed: int) -> Tuple[str, Dict[str, object]]:
        """Return (text, info). Text length is within one line of target_chars."""
        rng = Rng(seed)
        parts: List[str] = []
        size = 0
        index = 0
        tag = "%04x" % (seed & 0xFFFF)
        mixer = Mixer(rng) if self.kind == "diverse" else None
        chunks = self._file_sections(rng) if self.kind == "file" else None
        while size < target_chars:
            if mixer is not None:
                section = mixer.section()
            elif self.kind == "repetitive":
                section = repetitive_section(tag, index)
            else:
                assert chunks is not None
                section = next(chunks)
            parts.append(section)
            size += len(section) + 1
            index += 1
        text = "\n".join(parts)
        if len(text) > target_chars:
            cut = text.rfind("\n", 0, target_chars)
            text = text[: cut if cut > 0 else target_chars]
        info: Dict[str, object] = {
            "kind": self.kind,
            "seed": "%016x" % seed,
            "chars": len(text),
            "sections": index,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "compress_ratio": compress_ratio(text),
        }
        if self.kind == "file":
            info["source_sha256"] = self.file_sha256
            info["source_chars"] = self.file_chars
            # The prompt is longer than the files: their text repeats inside it.
            info["wrapped"] = len(text) > self.file_chars
        return text, info


def compress_ratio(text: str) -> float:
    """Raw bytes divided by zlib-compressed bytes. Higher means more repetitive text.

    Typical values: real source code 3 to 5, the v1 repeated template above 20.
    """
    raw = text.encode("utf-8")
    if not raw:
        return 0.0
    return round(len(raw) / len(zlib.compress(raw, 9)), 2)


# ---------------------------------------------------------------------- prompt builders

SYSTEM_REVIEW = "You are a careful senior software engineer. Analyze only the provided evidence."
SYSTEM_CHAT = "You are a clear technical writer. Follow the requested format."


def _system(text: str, nonce: str) -> str:
    # The run marker leads the very first message, so two runs share no prompt prefix
    # beyond the chat template's own opening tokens. A prefix cache has nothing to reuse.
    return "[run %s] %s" % (nonce, text)


def context_messages(corpus_text: str, nonce: str) -> List[Dict[str, str]]:
    user = (
        "Benchmark run %s. Review the following multi-file repository excerpts. "
        "Identify likely correctness, reliability, and performance risks supported by the excerpts. "
        "Prioritize concrete fixes, cite file names, and do not assume behavior that is not shown."
        "\n\nBEGIN REPOSITORY EXCERPTS\n%s\nEND REPOSITORY EXCERPTS\n"
        "Write a long, detailed, prioritized engineering review. Keep writing until you run out of space."
    ) % (nonce, corpus_text)
    return [{"role": "system", "content": _system(SYSTEM_REVIEW, nonce)}, {"role": "user", "content": user}]


def followup_messages(first_turn: List[Dict[str, str]], assistant_text: str, nonce: str, seed: int) -> List[Dict[str, str]]:
    focus = Rng(seed).pick(FOLLOWUP_FOCUS)
    question = (
        "Follow-up %s. Now look only at %s. List the most severe issues in that area with file names, "
        "then explain each fix in detail. Keep writing until you run out of space."
    ) % (nonce, focus)
    return list(first_turn) + [
        {"role": "assistant", "content": assistant_text or "Review complete."},
        {"role": "user", "content": question},
    ]


def chat_messages(nonce: str, seed: int) -> List[Dict[str, str]]:
    topic = Rng(seed).pick(CHAT_TOPICS)
    user = (
        "Session %s. Explain %s to a junior developer. Cover how it works, when to use it, "
        "two common pitfalls, and a short worked example. Write at least 900 words and do not stop early."
    ) % (nonce, topic)
    return [{"role": "system", "content": _system(SYSTEM_CHAT, nonce)}, {"role": "user", "content": user}]


SANITY_CHECKS = ("exact-word", "needle", "json")


def insert_lines(text: str, lines: Sequence[Tuple[float, str]]) -> str:
    """Insert each line at about the given fraction of the text, on a line boundary."""
    for fraction, line in sorted(lines, reverse=True):
        cut = text.find("\n", int(len(text) * fraction))
        cut = len(text) if cut < 0 else cut
        text = text[:cut] + "\n" + line + text[cut:]
    return text


def sanity_messages(check: str, nonce: str, seed: int, corpus_text: str = "") -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    """Build one exact-answer check. Returns (messages, expectation).

    These are not a quality score. They answer one question a speed test must not skip:
    is the model actually receiving the whole prompt and answering it?
    """
    rng = Rng(seed)
    system = {"role": "system", "content": _system("Answer precisely and briefly.", nonce)}
    if check == "exact-word":
        word = "%s-%d" % (rng.pick(NOUNS).upper(), rng.between(1000, 9999))
        return [system, {"role": "user", "content": "Reply with exactly this word and nothing else: %s" % word}], {"contains": [word]}
    if check == "json":
        a, b = rng.between(11, 89), rng.between(11, 89)
        user = 'Reply with only a JSON object that has two keys: "status" with the value "ok", and "sum" with the sum of %d and %d as a number.' % (a, b)
        return [system, {"role": "user", "content": user}], {"json": {"status": "ok", "sum": a + b}}
    if check == "needle":
        alpha = "%s%d" % (rng.pick(ADJS).upper(), rng.between(100, 999))
        omega = "%s%d" % (rng.pick(VERBS).upper(), rng.between(100, 999))
        # One marker near the start and one near the end: a runtime that drops the oldest
        # text, the middle or the tail loses at least one of them.
        body = insert_lines(corpus_text, ((0.10, "ACCESS-CODE-ALPHA = %s" % alpha), (0.90, "ACCESS-CODE-OMEGA = %s" % omega)))
        user = (
            "Run %s. Two access codes are hidden in the repository excerpts below."
            "\n\nBEGIN REPOSITORY EXCERPTS\n%s\nEND REPOSITORY EXCERPTS\n"
            "What are the values of ACCESS-CODE-ALPHA and ACCESS-CODE-OMEGA? Answer with just the two values."
        ) % (nonce, body)
        return [system, {"role": "user", "content": user}], {"contains": [alpha, omega]}
    raise ValueError("unknown sanity check %r" % check)


def message_chars(messages: List[Dict[str, str]]) -> int:
    return sum(len(m.get("content") or "") for m in messages)
