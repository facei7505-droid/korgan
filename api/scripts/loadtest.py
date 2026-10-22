"""Latency check for /v1/transfers/score.

    python scripts/loadtest.py --url http://localhost:8000 --n 2000 --concurrency 50
"""
import argparse
import asyncio
import random
import statistics
import time

import httpx


def card(prefix: str) -> str:
    digits = prefix + "".join(random.choice("0123456789") for _ in range(15 - len(prefix)))
    for d in "0123456789":
        s, parity = 0, (len(digits) + 1) % 2
        for i, ch in enumerate(digits + d):
            x = int(ch)
            if i % 2 == parity:
                x = x * 2 - 9 if x * 2 > 9 else x * 2
            s += x
        if s % 10 == 0:
            return digits + d
    raise AssertionError


async def main(url: str, n: int, concurrency: int) -> None:
    headers = {"X-API-Key": "dev-bank-key"}
    latencies: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=10) as client:
        async def one() -> None:
            nonlocal errors
            body = {
                "customer_id": "cus_demo_bibigul", "amount": random.choice([5000, 20000, 150000, 800000]),
                "recipient": {"kind": "card", "value": card("440043")},
                "behavior": {"max_pause_ms": random.randint(0, 15000), "pasted_recipient": random.random() < 0.3},
            }
            async with sem:
                t = time.perf_counter()
                r = await client.post("/v1/transfers/score", json=body)
                latencies.append((time.perf_counter() - t) * 1000)
                errors += r.status_code != 200

        start = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(n)))
        wall = time.perf_counter() - start

    latencies.sort()
    q = lambda p: latencies[min(len(latencies) - 1, int(p * len(latencies)))]  # noqa: E731
    print(f"requests={n} concurrency={concurrency} errors={errors} throughput={n / wall:.0f} rps")
    print(f"latency ms: p50={q(.5):.1f} p95={q(.95):.1f} p99={q(.99):.1f} mean={statistics.mean(latencies):.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--concurrency", type=int, default=20)
    a = ap.parse_args()
    asyncio.run(main(a.url, a.n, a.concurrency))
