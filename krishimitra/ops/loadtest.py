"""Rough load probe (not a benchmark). Usage: python ops/loadtest.py http://localhost:8080 [concurrency] [seconds]
Hits public/read endpoints; a real test needs authenticated, mixed traffic (use k6 or Locust) against production-like hardware."""
import sys, time, threading, statistics, httpx

base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
conc = int(sys.argv[2]) if len(sys.argv) > 2 else 50
secs = int(sys.argv[3]) if len(sys.argv) > 3 else 20
paths = ["/api/v1/health", "/api/v1/products", "/api/v1/categories"]
lat, errs = [], [0]
end = time.time() + secs

def worker():
    with httpx.Client(base_url=base, timeout=10) as c:
        i = 0
        while time.time() < end:
            t = time.perf_counter()
            try:
                r = c.get(paths[i % len(paths)]); i += 1
                if r.status_code >= 500: errs[0] += 1
            except Exception:
                errs[0] += 1
            lat.append((time.perf_counter() - t) * 1000)

ts = [threading.Thread(target=worker) for _ in range(conc)]
[t.start() for t in ts]; [t.join() for t in ts]
lat.sort()
print(f"requests={len(lat)} rps={len(lat)/secs:.0f} errors={errs[0]} p50={statistics.median(lat):.0f}ms p95={lat[int(len(lat)*.95)]:.0f}ms")
