#!/usr/bin/env python3
"""Generate the README GIF from real results over bundled synthetic fixtures."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "martech-change-guard" / "scripts" / "guard.py"
FIXTURES = ROOT / "fixtures"
OUT = ROOT / "docs" / "martech-change-guard-demo.gif"
WIDTH, HEIGHT = 1200, 680


def run(*args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


def stable(value):
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key != "created_at"}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def capture_reports():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        blocked_dir = root / "blocked"
        safe_dir = root / "safe"
        failed_dir = root / "failed"
        passed_dir = root / "passed"
        blocked = run("plan", "--before", FIXTURES / "current.csv", "--proposed",
                      FIXTURES / "proposed-blocked.csv", "--key", "record_id", "--policy",
                      FIXTURES / "policy.json", "--out", blocked_dir)
        safe = run("plan", "--before", FIXTURES / "current.csv", "--proposed",
                   FIXTURES / "proposed-safe.csv", "--key", "record_id", "--policy",
                   FIXTURES / "policy.json", "--out", safe_dir)
        failed = run("verify", "--before", FIXTURES / "current.csv", "--actual",
                     FIXTURES / "actual-side-effect.csv", "--key", "record_id", "--plan",
                     safe_dir, "--out", failed_dir)
        passed = run("verify", "--before", FIXTURES / "current.csv", "--actual",
                     FIXTURES / "actual-safe.csv", "--key", "record_id", "--plan",
                     safe_dir, "--out", passed_dir)
        expected = [(blocked, 2), (safe, 1), (failed, 1), (passed, 0)]
        for result, code in expected:
            if result.returncode != code:
                raise RuntimeError("demo command exited %d, expected %d: %s" %
                                   (result.returncode, code, result.stderr.strip()))
        return stable({
            "blocked": json.loads((blocked_dir / "risk-report.json").read_text(encoding="utf-8")),
            "safe": json.loads((safe_dir / "risk-report.json").read_text(encoding="utf-8")),
            "failed": json.loads((failed_dir / "verification.json").read_text(encoding="utf-8")),
            "passed": json.loads((passed_dir / "verification.json").read_text(encoding="utf-8")),
        })


def transcript(reports):
    blocked, safe = reports["blocked"], reports["safe"]
    failed, passed = reports["failed"], reports["passed"]
    codes = ", ".join(item["code"] for item in blocked["violations"][:3])
    return [
        ("prompt", "codex > $martech-change-guard Preflight this CRM update"),
        ("dim", "Reading current + proposed exports locally..."),
        ("text", ""),
        ("heading", "PLAN: BLOCK"),
        ("critical", "  Risk %d/100 (%s)" % (blocked["risk"]["score"], blocked["risk"]["level"])),
        ("critical", "  %s" % codes),
        ("text", ""),
        ("heading", "REVISED PLAN: %s" % safe["decision"].upper()),
        ("warn", "  %d records, %d approved field changes" %
         (safe["blast_radius"]["changed_records"], safe["blast_radius"]["field_changes"])),
        ("good", "  Deterministic canary + rollback + SHA-256-linked manifest"),
        ("text", ""),
        ("heading", "POST-CHANGE VERIFY"),
        ("critical", "  Side-effect fixture: %s (%d unexpected field change)" %
         (failed["status"].upper(), failed["summary"]["side_effects"])),
        ("good", "  Clean fixture: %s (full original scope checked)" % passed["status"].upper()),
        ("text", ""),
        ("dim", "No connector. No credentials. No live write. Synthetic fixtures only."),
    ]


def fingerprint(reports):
    source = pathlib.Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
    payload = json.dumps(reports, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((source + "\n" + payload).encode("utf-8")).hexdigest()


def marker(reports):
    return ("martech-change-guard-demo:" + fingerprint(reports)).encode("ascii")


def check(reports):
    if not OUT.is_file():
        print("MISSING %s - run python tools/make_demo_gif.py" % OUT.relative_to(ROOT), file=sys.stderr)
        return 1
    raw = OUT.read_bytes()
    if not raw.startswith((b"GIF87a", b"GIF89a")) or len(raw) < 10:
        print("INVALID %s - expected a GIF" % OUT.relative_to(ROOT), file=sys.stderr)
        return 1
    if struct.unpack("<HH", raw[6:10]) != (WIDTH, HEIGHT):
        print("INVALID %s - wrong dimensions" % OUT.relative_to(ROOT), file=sys.stderr)
        return 1
    if marker(reports) not in raw:
        print("STALE %s - run python tools/make_demo_gif.py" % OUT.relative_to(ROOT), file=sys.stderr)
        return 1
    print("%s matches the tool's current results" % OUT.relative_to(ROOT))
    return 0


def font(candidates, size):
    from PIL import ImageFont
    for candidate in candidates:
        if pathlib.Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    raise RuntimeError("could not find a usable font")


def generate(reports):
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("GIF generation requires Pillow") from exc
    mono = font(["C:/Windows/Fonts/consola.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"], 21)
    bold = font(["C:/Windows/Fonts/segoeuib.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"], 19)
    colours = {"bg": "#0b0f14", "panel": "#111821", "border": "#273241",
               "text": "#d7dee9", "dim": "#8290a3", "prompt": "#73e2a7",
               "heading": "#7dd3fc", "critical": "#ff7b72", "warn": "#f2cc60",
               "good": "#73e2a7"}
    lines = transcript(reports)

    def render(visible):
        image = Image.new("RGB", (WIDTH, HEIGHT), colours["bg"])
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((18, 18, WIDTH - 18, HEIGHT - 18), radius=15,
                               fill=colours["panel"], outline=colours["border"], width=2)
        for x, colour in ((42, "#ff5f57"), (64, "#febc2e"), (86, "#28c840")):
            draw.ellipse((x - 6, 32, x + 6, 44), fill=colour)
        draw.text((110, 26), "MarTech Change Guard - local CRM change control",
                  font=bold, fill=colours["dim"])
        draw.line((28, 62, WIDTH - 28, 62), fill=colours["border"])
        y = 84
        for style, value in visible:
            draw.text((48, y), value, font=mono, fill=colours.get(style, colours["text"]))
            y += 32
        draw.text((48, HEIGHT - 44), "Real tool results - bundled synthetic fixtures",
                  font=mono, fill=colours["dim"])
        return image

    frames, durations = [], []
    prompt_style, prompt = lines[0]
    for chars in range(0, len(prompt) + 1, 4):
        frames.append(render([(prompt_style, prompt[:chars] + ("_" if chars < len(prompt) else ""))]))
        durations.append(75)
    durations[-1] = 600
    for count in range(2, len(lines) + 1):
        frames.append(render(lines[:count]))
        durations.append(450 if lines[count - 1][0] == "heading" else 280)
    durations[-1] = 5000
    palette = frames[-1].quantize(colors=64)
    frames = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, optimize=True, disposal=2, comment=marker(reports))
    print("wrote %s" % OUT.relative_to(ROOT))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        reports = capture_reports()
        if "--check" in argv:
            return check(reports)
        generate(reports)
        return check(reports)
    except (OSError, RuntimeError) as exc:
        print("could not build demo: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
