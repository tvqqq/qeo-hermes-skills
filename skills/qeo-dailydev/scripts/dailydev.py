from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from dailydev_client import DailyDevClient, DailyDevError


def _source_name(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("handle") or value.get("id") or "")
    return str(value or "")


def _tag_names(value) -> list[str]:
    names: list[str] = []
    for item in value or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("id") or "")
        else:
            name = str(item)
        if name:
            names.append(name)
    return names


def normalize_post(raw: dict, origin: str, rank: int) -> dict:
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("title") or ""),
        "url": str(raw.get("url") or ""),
        "source": _source_name(raw.get("source")),
        "published_at": str(raw.get("publishedAt") or ""),
        "summary": str(raw.get("summary") or ""),
        "tags": _tag_names(raw.get("tags")),
        "read_time": int(raw.get("readTime") or 0),
        "upvotes": int(raw.get("numUpvotes") or 0),
        "comments": int(raw.get("numComments") or 0),
        "origins": [origin] if origin else [],
        "source_ranks": [int(rank)] if rank else [],
    }


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def merge_posts(records: list[dict]) -> list[dict]:
    merged: list[dict] = []
    by_id: dict[str, int] = {}
    by_url: dict[str, int] = {}

    for record in records:
        index = by_id.get(record.get("id")) if record.get("id") else None
        canonical = _canonical_url(record.get("url", ""))
        if index is None and canonical:
            index = by_url.get(canonical)

        if index is None:
            index = len(merged)
            merged.append(dict(record))
        else:
            current = merged[index]
            current["origins"] = list(
                dict.fromkeys(current.get("origins", []) + record.get("origins", []))
            )
            current["source_ranks"] = current.get("source_ranks", []) + record.get(
                "source_ranks", []
            )
            current["upvotes"] = max(
                int(current.get("upvotes", 0)), int(record.get("upvotes", 0))
            )
            current["comments"] = max(
                int(current.get("comments", 0)), int(record.get("comments", 0))
            )
            for field in ("summary", "source", "published_at", "url", "title"):
                if not current.get(field) and record.get(field):
                    current[field] = record[field]

        if record.get("id"):
            by_id[str(record["id"])] = index
        if canonical:
            by_url[canonical] = index

    return merged


def _parse_datetime(value: str):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def score_post(post: dict, now: datetime) -> float:
    score = 3.0 if "for_you" in post.get("origins", []) else 0.0

    ranks = [int(value) for value in post.get("source_ranks", []) if int(value) > 0]
    if ranks:
        score += max(0.0, 2.5 - 0.15 * (min(ranks) - 1))

    score += min(2.0, 0.5 * max(0, len(set(post.get("origins", []))) - 1))

    published = _parse_datetime(post.get("published_at", ""))
    if published is not None:
        age_days = max(0.0, (now - published).total_seconds() / 86400)
        if age_days <= 1:
            score += 2.0
        elif age_days <= 3:
            score += 1.5
        elif age_days <= 7:
            score += 1.0
        elif age_days <= 30:
            score += 0.25

    score += min(
        2.0,
        math.log1p(max(0, int(post.get("upvotes", 0)))) / 4
        + math.log1p(max(0, int(post.get("comments", 0)))) / 6,
    )
    return float(score)


def resolve_state_dir(env: Mapping[str, str] | None = None) -> Path:
    values = env or os.environ
    configured = values.get("QEO_DAILYDEV_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    hermes_home = values.get("HERMES_HOME")
    if hermes_home:
        return Path(hermes_home) / "state" / "qeo-dailydev"
    return Path.home() / ".hermes" / "state" / "qeo-dailydev"


def load_history(state_dir: Path, now: datetime) -> dict[str, str]:
    path = Path(state_dir) / "history.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8")).get("delivered", {})
    cutoff = now - timedelta(days=14)
    result: dict[str, str] = {}
    for post_id, delivered_at in data.items():
        parsed = _parse_datetime(delivered_at)
        if parsed is not None and parsed >= cutoff:
            result[str(post_id)] = str(delivered_at)
    return result


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        Path(temporary).replace(path)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass


def finalize_digest(state_dir: Path, selected: list[dict], now: datetime) -> dict:
    state_dir = Path(state_dir)
    latest = {"generated_at": now.isoformat(), "articles": selected}
    history = load_history(state_dir, now)
    for article in selected:
        if article.get("id"):
            history[str(article["id"])] = now.isoformat()

    newest = sorted(
        history.items(),
        key=lambda item: _parse_datetime(item[1])
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:300]

    _atomic_write_json(state_dir / "latest_digest.json", latest)
    _atomic_write_json(state_dir / "history.json", {"delivered": dict(newest)})
    return latest


def _response_data(payload: dict) -> list[dict]:
    data = payload.get("data", []) if isinstance(payload, dict) else []
    return data if isinstance(data, list) else []


def collect_candidates(
    client,
    clusters: list[dict],
    history: dict[str, str],
    now: datetime,
    *,
    max_candidates: int = 40,
    diagnostics: dict | None = None,
) -> list[dict]:
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.setdefault("failed_sources", [])
    records: list[dict] = []

    try:
        for rank, raw in enumerate(_response_data(client.get_for_you(limit=20)), 1):
            records.append(normalize_post(raw, "for_you", rank))
    except DailyDevError as exc:
        if exc.status in (401, 403):
            raise
        diagnostics["failed_sources"].append("for_you")
    except Exception:
        diagnostics["failed_sources"].append("for_you")

    for cluster in clusters:
        cluster_id = cluster["id"]
        query = cluster["query"]
        try:
            weekly = _response_data(
                client.recommend_keyword(query, limit=8, time_range="week")
            )
            for rank, raw in enumerate(weekly, 1):
                records.append(normalize_post(raw, cluster_id, rank))

            if len(weekly) < 3:
                monthly = _response_data(
                    client.recommend_keyword(query, limit=8, time_range="month")
                )
                for rank, raw in enumerate(monthly, 1):
                    records.append(normalize_post(raw, cluster_id, rank))
        except DailyDevError as exc:
            if exc.status in (401, 403):
                raise
            diagnostics["failed_sources"].append(cluster_id)
        except Exception:
            diagnostics["failed_sources"].append(cluster_id)

    if not records and len(diagnostics["failed_sources"]) == 1 + len(clusters):
        raise DailyDevError("daily.dev candidate collection failed")

    candidates = [
        post for post in merge_posts(records) if post.get("id") not in history
    ]
    for post in candidates:
        post["score"] = round(score_post(post, now), 6)
    candidates.sort(key=lambda post: (-post["score"], post.get("title", "").lower()))
    return candidates[:max_candidates]


def load_clusters() -> list[dict]:
    path = Path(__file__).resolve().parents[1] / "references" / "topics.json"
    return json.loads(path.read_text(encoding="utf-8"))["clusters"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_dir(args, env: Mapping[str, str]) -> Path:
    if getattr(args, "state_dir", None):
        return Path(args.state_dir).expanduser()
    return resolve_state_dir(env)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    candidates = commands.add_parser("candidates")
    candidates.add_argument("--limit", type=int, default=40)
    candidates.add_argument("--state-dir")

    recommend = commands.add_parser("recommend")
    recommend.add_argument("--mode", choices=["keyword", "semantic"], required=True)
    recommend.add_argument("--query", required=True)
    recommend.add_argument("--limit", type=int, default=10)
    recommend.add_argument("--time", default="month")

    latest = commands.add_parser("latest")
    latest.add_argument("--index", type=int)
    latest.add_argument("--state-dir")

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--input", required=True)
    finalize.add_argument("--ids", required=True)
    finalize.add_argument("--state-dir")
    return parser


def main(argv=None, env=None, client_factory=DailyDevClient) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    environment = env if env is not None else os.environ

    if args.command in ("candidates", "recommend"):
        token = str(environment.get("DAILY_DEV_API_TOKEN", "")).strip()
        if not token:
            parser.error("DAILY_DEV_API_TOKEN is required")
        client = client_factory(token)

    try:
        if args.command == "candidates":
            now = _now()
            diagnostics: dict = {}
            candidates = collect_candidates(
                client,
                load_clusters(),
                load_history(_state_dir(args, environment), now),
                now,
                max_candidates=args.limit,
                diagnostics=diagnostics,
            )
            output = {
                "generated_at": now.isoformat(),
                "candidates": candidates,
                "diagnostics": diagnostics,
            }
        elif args.command == "recommend":
            if args.mode == "keyword":
                payload = client.recommend_keyword(
                    args.query, limit=args.limit, time_range=args.time
                )
            else:
                payload = client.recommend_semantic(
                    args.query, limit=args.limit, time_range=args.time
                )
            output = {
                "query": args.query,
                "mode": args.mode,
                "results": [
                    normalize_post(raw, args.mode, rank)
                    for rank, raw in enumerate(_response_data(payload), 1)
                ],
            }
        elif args.command == "latest":
            path = _state_dir(args, environment) / "latest_digest.json"
            if not path.exists():
                parser.error("latest digest is not available")
            output = json.loads(path.read_text(encoding="utf-8"))
            if args.index is not None:
                articles = output.get("articles", [])
                if args.index < 1 or args.index > len(articles):
                    parser.error("latest digest index is out of range")
                output = articles[args.index - 1]
        else:
            bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
            by_id = {
                str(article.get("id")): article
                for article in bundle.get("candidates", [])
                if article.get("id")
            }
            selected_ids = [
                value.strip() for value in args.ids.split(",") if value.strip()
            ]
            if (
                not selected_ids
                or len(selected_ids) != len(set(selected_ids))
                or any(post_id not in by_id for post_id in selected_ids)
            ):
                parser.error(
                    "finalize ids must be unique candidate IDs from the input bundle"
                )
            output = finalize_digest(
                _state_dir(args, environment),
                [by_id[post_id] for post_id in selected_ids],
                _now(),
            )

        print(json.dumps(output, ensure_ascii=False))
        return 0
    except (DailyDevError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
