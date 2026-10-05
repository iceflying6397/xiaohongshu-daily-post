#!/usr/bin/env python3
"""Inspect or reserve one daily post directory without replacing existing work."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import uuid

MARKER = ".制作中.json"
DRAFTS = ("内容文稿.txt", "内容文稿.md")


def empty_slot(path, ignore_marker=False):
    if path.is_symlink() or not path.is_dir():
        return False
    for item in path.iterdir():
        if item.name == ".DS_Store" or (ignore_marker and item.name == MARKER):
            continue
        if item.name == "配图" and item.is_dir() and not item.is_symlink():
            if all(child.name == ".DS_Store" for child in item.iterdir()):
                continue
        return False
    return True


def inspect(root, date):
    day = root / date
    if day.is_symlink() or (day.exists() and not day.is_dir()):
        raise ValueError("日期路径不是普通目录，不能写入")
    entries = []
    if day.exists():
        for item in day.iterdir():
            if not re.fullmatch(r"[0-9]+", item.name) or int(item.name) < 1:
                continue
            number = int(item.name)
            entries.append({
                "number": number,
                "path": str(item),
                "empty": item.name == str(number) and empty_slot(item),
                "has_draft": not item.is_symlink() and item.is_dir()
                    and any((item / name).is_file() for name in DRAFTS),
            })
    entries.sort(key=lambda item: (item["number"], item["path"]))
    numbers = [item["number"] for item in entries]
    if len(set(numbers)) != len(numbers):
        raise ValueError("发现相同序号的多个路径（例如 1 和 01），请先明确目标目录")
    available = [item["number"] for item in entries if item["empty"]]
    candidate = min(available) if available else max(numbers, default=0) + 1
    return {
        "date": date,
        "written_count": sum(item["has_draft"] for item in entries),
        "occupied_count": sum(not item["empty"] for item in entries),
        "entries": entries,
        "next_number": candidate,
        "post_path": str(day / str(candidate)),
    }


def reserve(root, date):
    for _ in range(100):
        result = inspect(root, date)
        post = Path(result["post_path"])
        post.parent.mkdir(exist_ok=True)
        try:
            post.mkdir()
        except FileExistsError:
            if not empty_slot(post):
                continue
        token = uuid.uuid4().hex
        marker = post / MARKER
        try:
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"date": date, "number": result["next_number"],
                       "reservation_token": token}, stream, ensure_ascii=False)
        if not empty_slot(post, ignore_marker=True):
            marker.unlink()
            continue
        (post / "配图").mkdir(exist_ok=True)
        result["reservation_token"] = token
        result["reserved"] = True
        return result
    raise ValueError("目录持续发生并发变化，未能预留新图文")


def release(root, date, number, token):
    day = root / date
    post = day / str(number)
    marker = post / MARKER
    if day.is_symlink() or post.is_symlink() or marker.is_symlink():
        raise ValueError("不能清理符号链接路径")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if not token or data.get("reservation_token") != token:
        raise ValueError("制作标记不属于当前任务，不能清理")
    marker.unlink()
    return {"released": True, "date": date, "number": number, "post_path": str(post)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reserve", action="store_true")
    mode.add_argument("--release", type=int)
    parser.add_argument("--token")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
            raise ValueError("日期必须为 YYYY-MM-DD")
        datetime.date.fromisoformat(args.date)
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("项目根路径必须为目录")
        if args.release is not None:
            if args.release < 1:
                raise ValueError("序号必须大于零")
            result = release(root, args.date, args.release, args.token)
        else:
            result = reserve(root, args.date) if args.reserve else inspect(root, args.date)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"无法准备图文目录：{exc}\n")


if __name__ == "__main__":
    main()
