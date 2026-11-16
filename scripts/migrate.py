"""Claude native history transfer. Standard library, Python 3.10+."""
import argparse
from functools import lru_cache
import hashlib
import json
import os
import shutil
from pathlib import Path, PurePosixPath
import tempfile
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_json(p, fallback=None):
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else fallback


def exclusive(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("xb") as f:
        f.write(data)


def files_under(root, skipped):
    if not root.exists():
        return
    if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        skipped.append(str(root))
        return
    if root.is_file():
        yield root
        return
    for base, dirs, names in os.walk(root, followlinks=False):
        for d in list(dirs):
            p = Path(base) / d
            if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
                skipped.append(str(p))
                dirs.remove(d)
        for n in names:
            p = Path(base) / n
            if p.is_symlink():
                skipped.append(str(p))
            else:
                yield p


def source_inventory(profile, config):
    registry = read_json(profile / ".claude.json", {})
    candidates = set(registry.get("projects", {}).keys())
    histories = []
    for p in sorted((config / "projects").glob("*/*.jsonl")):
        cwd, title = None, None
        with p.open("r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if isinstance(obj.get("cwd"), str):
                    cwd = obj["cwd"]
                    candidates.add(cwd)
                if obj.get("type") == "custom-title":
                    title = obj.get("customTitle", title)
        histories.append({"directory": p.parent.name, "file": p.name, "cwd": cwd, "title": title})
    return {"profile": str(profile), "config": str(config), "histories": histories,
            "projectCandidates": [{"source": x, "exists": Path(x).is_dir()} for x in sorted(candidates)]}


def export_bundle(args):
    profile, config, out = args.profile.resolve(), args.config_dir.resolve(), args.out.resolve()
    if not config.is_dir():
        raise ValueError("Source configuration directory missing")
    if out.is_relative_to(config):
        raise ValueError("Output must be outside source configuration")
    selections = read_json(args.projects, []) if getattr(args, "projects", None) else []
    project_roots = []
    for index, value in enumerate(selections):
        source = Path(value["source"]).resolve()
        if not source.is_dir() or source == Path(source.anchor) or source == profile or source.is_relative_to(config) or config.is_relative_to(source):
            raise ValueError("Invalid or over-broad project root; select actual project directories")
        if out.is_relative_to(source) or source.is_relative_to(out):
            raise ValueError("Export output overlaps project root")
        if any(source.is_relative_to(Path(x["source"])) or Path(x["source"]).is_relative_to(source) for x in project_roots):
            raise ValueError("Overlapping project roots; select one root and map nested cwd with paths")
        project_roots.append({"id": f"p{index:04d}", "source": str(source)})
    out.mkdir(parents=True, exist_ok=False)
    skipped, entries = [], []
    archive = out / "claude-transfer.zip"
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as z:
        def archive_file(p, rel):
            if os.name == 'nt' and not str(p).startswith('\\\\?\\'):
                p = Path('\\\\?\\' + str(p.resolve()))
            before = p.stat()
            h, size = hashlib.sha256(), 0
            with p.open('rb') as src, z.open(rel, 'w', force_zip64=True) as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b''):
                    dst.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
            after = p.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or size != after.st_size:
                raise ValueError('Source changed during export; stop writers and retry')
            entries.append({'path': rel, 'size': size, 'sha256': h.hexdigest()})
        roots = ["projects", "skills", "commands", "agents", "file-history", "plugins",
                 "scheduled-tasks", "CLAUDE.md", "settings.json", "settings.local.json", "history.jsonl"]
        for name in roots:
            for p in files_under(config / name, skipped):
                rel = "config/" + p.relative_to(config).as_posix()
                archive_file(p, rel)
        for p in files_under(profile / ".agents" / "skills", skipped):
            rel = "shared/skills/" + p.relative_to(profile / ".agents" / "skills").as_posix()
            archive_file(p, rel)
        exclusions = []
        empty_dirs = []
        for item in project_roots:
            source = Path(item["source"])
            # Full working tree, including hidden project configuration and uncommitted files.
            # Generated dependencies are rebuilt; record every omitted directory.
            for base, dirs, names in os.walk(source, followlinks=False):
                for d in list(dirs):
                    p = Path(base) / d
                    if d in ("node_modules", ".venv", "venv", "__pycache__"):
                        exclusions.append(str(p))
                        dirs.remove(d)
                    elif p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
                        skipped.append(str(p))
                        dirs.remove(d)
                relbase = Path(base).relative_to(source)
                if not dirs and not names:
                    empty_dirs.append({"project": item["id"], "path": relbase.as_posix()})
                for n in names:
                    p = Path(base) / n
                    if p.is_symlink():
                        skipped.append(str(p))
                        continue
                    rel = "workspaces/" + item["id"] + "/" + p.relative_to(source).as_posix()
                    archive_file(p, rel)
        # Only transferable registry fields: exclude identity, OAuth and machine caches.
        registry = read_json(profile / ".claude.json", {})
        portable = {"mcpServers": registry.get("mcpServers", {}), "projects": {}}
        for cwd, value in registry.get("projects", {}).items():
            if isinstance(value, dict):
                portable["projects"][cwd] = {k: value[k] for k in ("mcpServers",) if k in value}
        raw = dump(portable)
        rel = "registry/portable.json"
        z.writestr(rel, raw)
        entries.append({"path": rel, "size": len(raw), "sha256": digest(raw)})
        manifest = {"format": 1, "sourceProfile": str(profile), "sourceConfig": str(config),
                    "entries": entries, "skippedLinks": skipped, "projectRoots": project_roots,
                    "excludedDependencies": exclusions, "emptyProjectDirectories": empty_dirs}
        z.writestr("manifest.json", dump(manifest))
    # Stream the archive checksum without loading a multi-GB archive into memory.
    with archive.open("rb") as f:
        h = hashlib.file_digest(f, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else stream_hash(f)
    exclusive(out / "claude-transfer.zip.sha256", (h + "\n").encode("ascii"))
    return {"archive": str(archive), "files": len(entries), "projects": len(project_roots), "skippedLinks": len(skipped), "sha256": h}


def stream_hash(f):
    h = hashlib.sha256()
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
    return h.hexdigest()


def safe_relative(name):
    p = PurePosixPath(name)
    if "\\" in name or ":" in name or p.is_absolute() or any(x in ("..", ".") for x in p.parts):
        raise ValueError("Unsafe bundle path")
    if not p.parts or str(p) != name or any(x.endswith((" ", ".")) for x in p.parts):
        raise ValueError("Noncanonical bundle path")
    reserved = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}
    if any(x.split(".")[0].upper() in reserved for x in p.parts):
        raise ValueError("Reserved Windows path")
    return p


@lru_cache(maxsize=None)
def checked_parent(root, parent):
    if parent != root:
        if not parent.is_relative_to(root):
            raise ValueError('Destination escapes root')
        checked_parent(root, parent.parent)
    if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
        raise ValueError('Destination contains a link or junction')


def destination(root, rel):
    safe_relative(rel)
    p = root.joinpath(*PurePosixPath(rel).parts)
    # Cache stable parents within this offline run, but inspect each final path.
    checked_parent(root, p.parent)
    if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
        raise ValueError('Destination contains a link or junction')
    if os.name == 'nt' and len(str(p)) >= 240 and not str(p).startswith('\\\\?\\'):
        return Path('\\\\?\\' + str(p.resolve()))
    return p


def mapped_path(text, mapping):
    for old, new in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
        if text.lower() == old.lower() or text.lower().startswith(old.rstrip("\\/").lower() + "\\") or text.lower().startswith(old.rstrip("\\/").lower() + "/"):
            return new.rstrip("\\/") + text[len(old.rstrip("\\/")):]
    return text


def map_config(obj, paths):
    if isinstance(obj, dict):
        return {k: map_config(v, paths) for k, v in obj.items()}
    if isinstance(obj, list):
        return [map_config(v, paths) for v in obj]
    return mapped_path(obj, paths) if isinstance(obj, str) else obj


def transform(data, rel, paths):
    # Only top-level structural cwd. Never rewrite quoted prompts/tool history.
    if not paths or not rel.endswith(".jsonl") or not rel.startswith("projects/"):
        return data
    lines = []
    for line in data.splitlines(keepends=True):
        try:
            obj = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            lines.append(line)
            continue
        if isinstance(obj, dict) and isinstance(obj.get("cwd"), str):
            new = mapped_path(obj["cwd"], paths)
            if new != obj["cwd"]:
                obj["cwd"] = new
                line = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        lines.append(line)
    return b"".join(lines)


def merge_missing(target, source, conflicts, prefix="", atomic=False):
    for k, v in source.items():
        field = prefix + "/" + k
        if k not in target:
            target[k] = v
        elif target[k] == v:
            pass
        elif isinstance(target[k], dict) and isinstance(v, dict) and not atomic:
            merge_missing(target[k], v, conflicts, field, atomic=(k == "mcpServers"))
        else:
            conflicts.append(field)


def migration(args):
    checked_parent.cache_clear()
    profile, config, out = args.profile.resolve(), args.config_dir.resolve(), args.out.resolve()
    if out.is_relative_to(config) or out.is_relative_to(profile / ".agents" / "skills"):
        raise ValueError("Output must be outside live configuration")
    if args.mode == "apply" and not args.writers_stopped:
        raise ValueError("apply requires --writers-stopped after closing Claude writers")
    mapping = read_json(args.map, {}) if args.map else {}
    paths, dirs = mapping.get("paths", {}), mapping.get("projectDirs", {})
    for a, b in dirs.items():
        if len(safe_relative(a).parts) != 1 or len(safe_relative(b).parts) != 1:
            raise ValueError("Project directory mappings must be single directory names")
    if len({v.casefold() for v in dirs.values()}) != len(dirs):
        raise ValueError("Project directory mapping is not one-to-one")
    out.mkdir(parents=True, exist_ok=False)
    report = {"mode": args.mode, "new": [], "same": [], "conflicts": [], "review": [], "configMerges": []}
    with zipfile.ZipFile(args.bundle) as z:
        names = z.namelist()
        if len({x.casefold() for x in names}) != len(names):
            raise ValueError("Duplicate bundle members")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format") != 1:
            raise ValueError("Unsupported bundle version")
        entries = manifest["entries"]
        if set(names) != {"manifest.json", *[e["path"] for e in entries]}:
            raise ValueError("Bundle manifest coverage mismatch")
        # Validate every member and hash before any destination write.
        for e in entries:
            safe_relative(e["path"])
            info = z.getinfo(e["path"])
            if info.file_size != e["size"] or info.file_size > 16 * 1024 ** 3:
                raise ValueError("Invalid or excessively large bundle member")
            with z.open(e['path']) as src:
                if stream_hash(src) != e['sha256']:
                    raise ValueError("Bundle member hash mismatch")
        entry_hashes = {e['path']: e['sha256'] for e in entries}
        def payload_hash(name, raw):
            return entry_hashes[name] if raw is None else digest(raw)
        def existing_hash(p):
            with p.open('rb') as src:
                return stream_hash(src)
        def write_payload(p, name, raw):
            if raw is not None:
                exclusive(p, raw)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, p.open('xb') as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
        workspace_roots = {}
        for item in manifest.get("projectRoots", []):
            source = item["source"]
            if source not in mapping.get("workspaces", {}):
                raise ValueError("Every workspace source needs an explicit workspaces destination mapping")
            target = Path(mapping["workspaces"][source])
            if not target.is_absolute():
                raise ValueError("Workspace destination must be absolute")
            target = target.resolve()
            if target == Path(target.anchor) or target == profile or target.is_relative_to(config) or config.is_relative_to(target) or target.is_relative_to(out) or out.is_relative_to(target):
                raise ValueError("Invalid workspace destination")
            if any(target.is_relative_to(t) or t.is_relative_to(target) for t in workspace_roots.values()):
                raise ValueError("Overlapping workspace destinations")
            workspace_roots[item["id"]] = target
        report["projectRoots"] = {k: str(v) for k, v in workspace_roots.items()}
        report["sourceSkippedLinks"] = manifest.get("skippedLinks", [])
        report["excludedDependencies"] = manifest.get("excludedDependencies", [])
        incoming = []
        review_config = {}
        for e in entries:
            name, raw = e["path"], None
            if name.startswith("workspaces/"):
                _, project_id, rel = name.split("/", 2)
                root = workspace_roots[project_id]
                relparts = PurePosixPath(rel).parts
                if '.git' in relparts or relparts[-1] == '.mcp.json' or (len(relparts) >= 2 and relparts[-2] == '.claude' and relparts[-1] in ('settings.json', 'settings.local.json')):
                    report["review"].append(name)
                    if args.mode == "apply":
                        write_payload(destination(out / "review", name), name, raw)
                    continue
                # Prefix logical rel to avoid treating repository "projects/" as Claude history.
                incoming.append((name, destination(root, rel), raw, "workspace/" + project_id + "/" + rel))
                continue
            elif name.startswith("shared/"):
                root, rel = profile / ".agents", name[len("shared/"):]
                if not rel.startswith("skills/"):
                    raise ValueError("Unexpected shared resource")
            elif name.startswith("config/"):
                root, rel = config, name[len("config/"):]
                allowed = {"projects", "skills", "commands", "agents", "file-history", "plugins", "scheduled-tasks", "CLAUDE.md", "settings.json", "settings.local.json", "history.jsonl"}
                if rel.split("/")[0] not in allowed:
                    raise ValueError("Unexpected configuration root")
            elif name == "registry/portable.json":
                raw = z.read(name)
                review_config["registry"] = json.loads(raw)
                report["review"].append(name)
                if args.mode == "apply":
                    exclusive(destination(out / "review", name), raw)
                continue
            else:
                raise ValueError("Unexpected bundle member")
            original_rel = rel
            parts = rel.split("/")
            if parts[0] == "projects" and len(parts) > 1:
                parts[1] = dirs.get(parts[1], parts[1])
                rel = "/".join(parts)
            if original_rel in ("settings.json", "settings.local.json"):
                raw = z.read(name)
                review_config[original_rel] = json.loads(raw)
                continue
            if original_rel.startswith(("plugins/", "scheduled-tasks/")) or original_rel == "history.jsonl" or original_rel.endswith("sessions-index.json"):
                report["review"].append(name)
                if args.mode == "apply":
                    write_payload(destination(out / "review", name), name, raw)
                continue
            if rel.startswith('projects/') and rel.endswith('.jsonl') and paths:
                raw = transform(z.read(name), rel, paths)
            incoming.append((name, destination(root, rel), raw, rel))
        dests = [str(p).casefold() for _, p, _, _ in incoming]
        if len(set(dests)) != len(dests):
            raise ValueError("Multiple source files map to one destination")
        # If the primary UUID differs, quarantine the entire source UUID unit.
        blocked = set()
        blocked_skills = set()
        for name, p, raw, rel in incoming:
            parts = rel.split("/")
            if parts[0] == "skills" and len(parts) >= 3:
                skill_root = p.parents[len(parts) - 3]
                if skill_root.exists() and (not p.exists() or existing_hash(p) != payload_hash(name, raw)):
                    blocked_skills.add(str(skill_root).casefold())
        existing_uuid = {}
        if (config / "projects").exists():
            for p in (config / "projects").glob("*/*.jsonl"):
                existing_uuid.setdefault(p.stem.lower(), []).append(p)
        for name, p, raw, rel in incoming:
            parts = rel.split("/")
            if len(parts) == 3 and parts[0] == "projects" and rel.endswith(".jsonl"):
                peers = existing_uuid.get(p.stem.lower(), [])
                if any(q != p or existing_hash(q) != payload_hash(name, raw) for q in peers):
                    blocked.add((parts[1], p.stem))
        for name, p, raw, rel in incoming:
            parts = rel.split("/")
            unit = (parts[1], parts[2].removesuffix(".jsonl")) if len(parts) >= 3 and parts[0] == "projects" else None
            skill_blocked = parts[0] == "skills" and len(parts) >= 3 and str(p.parents[len(parts) - 3]).casefold() in blocked_skills
            if unit in blocked or skill_blocked or (p.exists() and existing_hash(p) != payload_hash(name, raw)):
                report["conflicts"].append({"source": name, "destination": str(p), "existingSha256": existing_hash(p) if p.is_file() else None})
                if args.mode == "apply":
                    write_payload(destination(out / "conflicts", name), name, raw)
            elif p.exists():
                report["same"].append(str(p))
            else:
                report["new"].append({"path": str(p), "sha256": payload_hash(name, raw)})
                if args.mode == "apply":
                    write_payload(p, name, raw)
                    with (out / "operations.jsonl").open("ab") as journal:
                        journal.write((json.dumps({"operation": "created", "path": str(p), "sha256": payload_hash(name, raw)}, ensure_ascii=False) + "\n").encode("utf-8"))
        # Preserve B identity. Merge only missing registry entries, not cached account state.
        registry = review_config.pop("registry", {})
        registry["projects"] = {mapped_path(k, paths): v for k, v in registry.get("projects", {}).items()}
        registry = map_config(registry, paths)
        config_inputs = [(profile / ".claude.json", registry)]
        for name, settings in review_config.items():
            # Conservative auto-merge of ordinary preferences; executable/security settings reviewed separately.
            safe = {k: v for k, v in settings.items() if k in ("model", "language", "outputStyle", "alwaysThinkingEnabled")}
            config_inputs.append((config / name, safe))
            report["review"].append(name)
            if args.mode == "apply":
                exclusive(destination(out / "review", name), dump(settings))
        for p, source in config_inputs:
            destination(p.parent.resolve(), p.name)
            before = p.read_bytes() if p.exists() else None
            current = json.loads(before.decode("utf-8-sig")) if before else {}
            conflicts = []
            merge_missing(current, source, conflicts)
            raw = dump(current)
            changed = bool(source) and (before is None or current != json.loads(before.decode("utf-8-sig")))
            report["configMerges"].append({"path": str(p), "changed": changed, "conflictKeys": conflicts})
            if args.mode == "apply" and changed:
                if before is not None:
                    exclusive(out / "backups" / ("registry.json" if p.name == ".claude.json" else p.name), before)
                    if p.read_bytes() != before:
                        raise ValueError("Configuration changed during apply; stop all writers")
                    fd, tmp = tempfile.mkstemp(prefix=".claude-migrate-", dir=p.parent)
                    with os.fdopen(fd, "wb") as f:
                        f.write(raw)
                    os.replace(tmp, p)
                else:
                    exclusive(p, raw)
                with (out / "operations.jsonl").open("ab") as journal:
                    journal.write((json.dumps({"operation": "merged-config", "path": str(p), "beforeSha256": digest(before) if before else None, "sha256": digest(raw)}, ensure_ascii=False) + "\n").encode("utf-8"))
        if args.mode == "apply":
            for item in report["new"]:
                if existing_hash(Path(item["path"])) != item["sha256"]:
                    raise ValueError("Post-write verification failed")
        report["emptyProjectDirectories"] = []
        for item in manifest.get("emptyProjectDirectories", []):
            root = workspace_roots[item["project"]]
            p = root if item["path"] == "." else destination(root, item["path"])
            report["emptyProjectDirectories"].append(str(p))
            if args.mode == "apply":
                p.mkdir(parents=True, exist_ok=True)
        report["counts"] = {k: len(report[k]) for k in ("new", "same", "conflicts", "review")}
        exclusive(out / (args.mode + "-report.json"), dump(report))
    return {"report": str(out / (args.mode + "-report.json")), "counts": report["counts"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["inventory", "export", "plan", "apply"])
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--config-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--bundle", type=Path)
    p.add_argument("--map", type=Path)
    p.add_argument("--projects", type=Path, help="Export selection: JSON array of {source: absolute project root}")
    p.add_argument("--writers-stopped", action="store_true")
    args = p.parse_args()
    if args.mode in ("plan", "apply") and not args.bundle:
        p.error("--bundle required")
    try:
        if args.mode == "inventory":
            args.out.mkdir(parents=True, exist_ok=False)
            result = source_inventory(args.profile.resolve(), args.config_dir.resolve())
            exclusive(args.out / "inventory.json", dump(result))
            print(json.dumps({"inventory": str(args.out / "inventory.json"), "histories": len(result["histories"]), "projectCandidates": len(result["projectCandidates"])}))
        else:
            print(json.dumps(export_bundle(args) if args.mode == "export" else migration(args), ensure_ascii=False))
    except Exception as e:
        # Avoid printing arbitrary source content or JSON parse fragments containing secrets.
        print(json.dumps({"errorType": type(e).__name__, "message": "Migration stopped; retain run directory and inspect locally."}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
