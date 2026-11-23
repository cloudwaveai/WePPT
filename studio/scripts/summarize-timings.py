"""Summarize WePPT's JSONL timing records without printing project contents."""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def summarize(records):
    groups = defaultdict(list)
    for record in records:
        duration = record.get("totalMs")
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            raise ValueError("Invalid totalMs in timing record")
        groups[record.get("action") or "(unspecified)"].append(duration)

    def stats(values):
        ordered = sorted(values)
        return {
            "count": len(ordered),
            "p50Seconds": round(ordered[math.ceil(len(ordered) * 0.5) - 1] / 1000, 2),
            "p90Seconds": round(ordered[math.ceil(len(ordered) * 0.9) - 1] / 1000, 2),
        }

    durations = [duration for values in groups.values() for duration in values]
    return {
        "overall": stats(durations) if durations else {"count": 0},
        "byAction": {action: stats(values) for action, values in sorted(groups.items())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timings", type=Path)
    args = parser.parse_args()
    with args.timings.open(encoding="utf-8") as stream:
        result = summarize(json.loads(line) for line in stream if line.strip())
    print(json.dumps(result, ensure_ascii=False, indent=2))
