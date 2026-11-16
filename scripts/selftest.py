"""Synthetic-only integration checks. Never reads real Claude state."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

SCRIPT = Path(__file__).with_name("migrate.py")
spec = importlib.util.spec_from_file_location("migration", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def put(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(m.dump(obj) if isinstance(obj, dict) else obj)
    return p


with tempfile.TemporaryDirectory(prefix="claude-transfer-test-") as tmp:
    root = Path(tmp)
    a, b = root / "A", root / "B"
    ac, bc = a / ".claude", b / ".claude"
    session = b'{"type":"custom-title","customTitle":"Original title","sessionId":"one"}\n{"cwd":"D:\\\\old","message":{"content":"D:\\\\old must stay literal"}}\n'
    put(ac, "projects/D--old/one.jsonl", session)
    put(ac, "projects/D--old/one/custom-title.json", {"customTitle": "Original title"})
    put(ac, "projects/D--old/two.jsonl", b'{"sessionId":"two","message":"A version"}\n')
    put(ac, "projects/D--old/two/custom-title.json", {"customTitle": "A title"})
    put(ac, "projects/D--old/memory/MEMORY.md", b"project memory")
    put(ac, "skills/example/SKILL.md", b"A skill")
    put(ac, "skills/collision/SKILL.md", b"A version")
    put(ac, "skills/collision/scripts/helper.py", b"A helper")
    put(ac, "settings.json", {"language": "zh", "hooks": {"SessionStart": "test"}, "env": {"SECRET": "test-only"}})
    put(ac, ".credentials.json", {"token": "must-not-export"})
    put(a, ".claude.json", {"oauthAccount": "A identity", "mcpServers": {"same": {"command": "A"}, "new": {"command": "python"}}})
    existing = put(bc, "projects/E--new/two.jsonl", b'{"sessionId":"two","message":"B version"}\n')
    b_hash = m.digest(existing.read_bytes())
    put(bc, "projects/E--new/two/custom-title.json", {"customTitle": "B title"})
    put(b, ".claude.json", {"oauthAccount": "B identity", "mcpServers": {"same": {"command": "B"}}})
    put(bc, "skills/collision/SKILL.md", b"B version")
    mapping = put(root, "mapping.json", {"paths": {r"D:\old": r"E:\new"}, "projectDirs": {"D--old": "E--new"}})
    project_a, project_b = root / "Aproject", root / "Bproject"
    put(project_a, "src/uncommitted.py", b"uncommitted source")
    put(project_a, "CLAUDE.md", b"project instructions")
    put(project_a, ".claude/agents/example.md", b"project agent")
    put(project_a, ".mcp.json", {"mcpServers": {"project": {"command": "python"}}})
    put(project_a, ".git/config", b"git metadata")
    put(project_a, "node_modules/unused.js", b"dependency")
    (project_a / "empty-folder").mkdir()
    selection = put(root, "projects.json", json.dumps([{"source": str(project_a)}]).encode())
    map_obj = json.loads(mapping.read_bytes())
    map_obj["workspaces"] = {str(project_a): str(project_b)}
    mapping.write_bytes(m.dump(map_obj))
    export = root / "export"
    m.export_bundle(SimpleNamespace(profile=a, config_dir=ac, out=export, projects=selection))
    args = SimpleNamespace(mode="plan", profile=b, config_dir=bc, out=root / "plan", bundle=export / "claude-transfer.zip", map=mapping, writers_stopped=True)
    m.migration(args)
    assert not (bc / "projects/E--new/one.jsonl").exists(), "plan wrote destination"
    args.mode, args.out = "apply", root / "apply"
    m.migration(args)
    assert m.digest(existing.read_bytes()) == b_hash, "B session overwritten"
    assert json.loads((bc / "projects/E--new/two/custom-title.json").read_bytes())["customTitle"] == "B title"
    assert (args.out / "conflicts/config/projects/D--old/two/custom-title.json").exists()
    registry = json.loads((b / ".claude.json").read_bytes())
    assert registry["oauthAccount"] == "B identity"
    assert registry["mcpServers"]["same"] == {"command": "B"}
    assert registry["mcpServers"]["new"] == {"command": "python"}
    assert not (bc / ".credentials.json").exists()
    assert "hooks" not in json.loads((bc / "settings.json").read_bytes())
    assert (bc / "projects/E--new/one/custom-title.json").exists()
    assert not (bc / "skills/collision/scripts/helper.py").exists(), "mixed same-name skill"
    assert (project_b / "src/uncommitted.py").read_bytes() == b"uncommitted source"
    assert (project_b / ".claude/agents/example.md").exists()
    assert (project_b / "empty-folder").is_dir()
    assert not (project_b / "node_modules").exists()
    assert not (project_b / ".git").exists()
    assert (args.out / "review/workspaces/p0000/.git/config").exists()
    assert (args.out / "review/workspaces/p0000/.mcp.json").exists()
    args.out = root / "again"
    m.migration(args)
    report = json.loads((args.out / "apply-report.json").read_bytes())
    assert len(report["new"]) == 0, "repeat created files"
    # Mapping must preserve historical message text while remapping structural cwd.
    raw = (json.dumps({"cwd": r"D:\old", "message": {"content": r"D:\old"}}) + "\n").encode()
    obj = json.loads(m.transform(raw, "projects/X/x.jsonl", {r"D:\old": r"E:\new"}))
    assert obj["cwd"] == r"E:\new" and obj["message"]["content"] == r"D:\old"
    for bad in ("../escape", "config/C:escape", "config/NUL.txt", "config/.. /escape"):
        try:
            m.safe_relative(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe path accepted")
    print("PASS: append, UUID-unit quarantine, B identity, atomic MCP conflicts, review-only hooks, repeat no-op, path fidelity, traversal rejection")
