#!/usr/bin/env python3
"""Build the connected MarTech Verify -> Change Guard GIF and MP4 walkthrough.

Generation runs both repositories over synthetic fixtures. Checking is dependency-free and
validates the committed provenance plus embedded media fingerprints.

    python tools/make_connected_demo.py --verify-repo ../martech-verify
    python tools/make_connected_demo.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "skills" / "martech-change-guard" / "scripts" / "guard.py"
FIXTURES = ROOT / "fixtures" / "connected"
DATA = ROOT / "docs" / "martech-ops-loop-data.json"
GIF = ROOT / "docs" / "martech-ops-loop-demo.gif"
MP4 = ROOT / "docs" / "martech-ops-loop-walkthrough.mp4"
WIDTH, HEIGHT, FPS = 1200, 720, 10


def run(command, expected):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env)
    if result.returncode != expected:
        detail = (result.stderr or result.stdout or "no output").strip()
        raise RuntimeError("command exited %d, expected %d: %s" %
                           (result.returncode, expected, detail))
    return result


def git_head(repo):
    result = run(["git", "-C", str(repo), "rev-parse", "HEAD"], 0)
    return result.stdout.strip()


def stable(value):
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key != "created_at"}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def capture(verify_repo):
    verify_repo = verify_repo.resolve()
    simulator = verify_repo / "skills" / "routing-simulate" / "scripts" / "simulate.py"
    if not simulator.is_file():
        raise RuntimeError("MarTech Verify was not found at %s" % verify_repo)
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        routing = run([
            sys.executable, str(simulator), "--rules",
            str(verify_repo / "fixtures" / "routing-simulate" / "routing_rules.json"),
            "--leads", str(verify_repo / "fixtures" / "routing-simulate" / "leads_sample.csv"),
            "--json",
        ], 1)
        routing_report = work / "routing-audit.json"
        routing_report.write_text(
            json.dumps(json.loads(routing.stdout), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        plan, failed_dir, passed_dir = work / "plan", work / "failed", work / "passed"
        run([
            sys.executable, str(GUARD), "plan", "--before",
            str(FIXTURES / "current-unrouted-leads.csv"), "--proposed",
            str(FIXTURES / "proposed-routed-leads.csv"), "--key", "lead_id", "--policy",
            str(FIXTURES / "routing-policy.json"), "--evidence", str(routing_report),
            "--reason", "Route nine leads identified as unassigned by MarTech Verify",
            "--out", str(plan),
        ], 1)
        run([
            sys.executable, str(GUARD), "verify", "--before",
            str(FIXTURES / "current-unrouted-leads.csv"), "--actual",
            str(FIXTURES / "actual-routed-side-effect.csv"), "--key", "lead_id",
            "--plan", str(plan), "--out", str(failed_dir),
        ], 1)
        run([
            sys.executable, str(GUARD), "verify", "--before",
            str(FIXTURES / "current-unrouted-leads.csv"), "--actual",
            str(FIXTURES / "actual-routed-safe.csv"), "--key", "lead_id",
            "--plan", str(plan), "--out", str(passed_dir),
        ], 0)
        changeset = json.loads((plan / "changeset.json").read_text(encoding="utf-8"))
        return stable({
            "schema_version": "1.0",
            "provenance": {
                "martech_verify": {
                    "repository": "https://github.com/m7mdwb/martech-verify",
                    "commit": git_head(verify_repo),
                    "skill": "routing-simulate",
                },
                "martech_change_guard": {
                    "repository": "https://github.com/m7mdwb/martech-change-guard",
                    "commit": git_head(ROOT),
                    "skill": "martech-change-guard",
                },
                "data": "Bundled synthetic fixtures only",
            },
            "martech_verify": json.loads(routing.stdout),
            "martech_change_guard": {
                "reason": changeset["reason"],
                "evidence_sha256": changeset["sources"]["evidence"][0]["sha256"],
                "plan": json.loads((plan / "risk-report.json").read_text(encoding="utf-8")),
                "failed_verification": json.loads(
                    (failed_dir / "verification.json").read_text(encoding="utf-8")),
                "passed_verification": json.loads(
                    (passed_dir / "verification.json").read_text(encoding="utf-8")),
            },
        })


def lines(data):
    audit = data["martech_verify"]
    guard = data["martech_change_guard"]
    plan = guard["plan"]
    failed = guard["failed_verification"]
    passed = guard["passed_verification"]
    return [
        ("prompt", "codex > $martech-audit Audit this lead-routing export"),
        ("dim", "MarTech Verify - read-only diagnosis"),
        ("critical", "  %d of %d leads are unrouted (%d%%)" %
         (audit["unrouted"], audit["leads"], round(audit["unrouted"] / audit["leads"] * 100))),
        ("critical", "  High intent trial uses unknown field 'employes'"),
        ("warn", "  France mid-market matched 3 leads and won none"),
        ("text", ""),
        ("prompt", "codex > Route those 9 leads safely; protect consent"),
        ("dim", "Handoff - audit report bound by SHA-256"),
        ("heading", "MarTech Change Guard - PLAN %s" % plan["decision"].upper()),
        ("warn", "  Risk %d/100 - %d records - %d approved owner changes" %
         (plan["risk"]["score"], plan["blast_radius"]["changed_records"],
          plan["blast_radius"]["field_changes"])),
        ("good", "  Canary + rollback generated; live write remains separate"),
        ("text", ""),
        ("heading", "POST-CHANGE VERIFY"),
        ("critical", "  First export: %s - %d consent side effect caught" %
         (failed["status"].upper(), failed["summary"]["side_effects"])),
        ("good", "  Corrected export: %s - receipt linked to exact evidence" %
         passed["status"].upper()),
        ("text", ""),
        ("dim", "Diagnose -> plan -> approve elsewhere -> verify"),
        ("good", "No connectors. No credentials. No autonomous write."),
    ]


def fingerprint(data):
    source = pathlib.Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((source + "\n" + payload).encode("utf-8")).hexdigest()


def marker(data):
    return ("martech-ops-loop:" + fingerprint(data)).encode("ascii")


def check():
    if not DATA.is_file():
        print("MISSING %s" % DATA.relative_to(ROOT), file=sys.stderr)
        return 1
    data = json.loads(DATA.read_text(encoding="utf-8"))
    expected = marker(data)
    if not GIF.is_file() or not MP4.is_file():
        print("MISSING connected walkthrough media", file=sys.stderr)
        return 1
    gif = GIF.read_bytes()
    if (not gif.startswith((b"GIF87a", b"GIF89a")) or len(gif) < 10 or
            struct.unpack("<HH", gif[6:10]) != (WIDTH, HEIGHT) or expected not in gif):
        print("INVALID or STALE %s" % GIF.relative_to(ROOT), file=sys.stderr)
        return 1
    mp4 = MP4.read_bytes()
    if len(mp4) < 12 or mp4[4:8] != b"ftyp" or expected not in mp4:
        print("INVALID or STALE %s" % MP4.relative_to(ROOT), file=sys.stderr)
        return 1
    print("connected GIF and MP4 match their real-output provenance")
    return 0


def find_font(candidates, size):
    from PIL import ImageFont
    for candidate in candidates:
        if pathlib.Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    raise RuntimeError("could not find a usable font")


def render_frames(data):
    from PIL import Image, ImageDraw
    mono = find_font(["C:/Windows/Fonts/consola.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"], 20)
    bold = find_font(["C:/Windows/Fonts/segoeuib.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"], 19)
    colours = {"bg": "#081018", "panel": "#101923", "border": "#294052",
               "text": "#d9e2ec", "dim": "#8ba0b3", "prompt": "#67e8a5",
               "heading": "#7dd3fc", "critical": "#ff7b72", "warn": "#f2cc60",
               "good": "#67e8a5"}
    transcript = lines(data)

    def render(visible):
        image = Image.new("RGB", (WIDTH, HEIGHT), colours["bg"])
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((18, 18, WIDTH - 18, HEIGHT - 18), radius=15,
                               fill=colours["panel"], outline=colours["border"], width=2)
        for x, colour in ((42, "#ff5f57"), (64, "#febc2e"), (86, "#28c840")):
            draw.ellipse((x - 6, 32, x + 6, 44), fill=colour)
        draw.text((110, 26), "The MarTech safety loop - real synthetic run",
                  font=bold, fill=colours["dim"])
        draw.line((28, 62, WIDTH - 28, 62), fill=colours["border"])
        y = 80
        for style, value in visible:
            draw.text((48, y), value, font=mono, fill=colours.get(style, colours["text"]))
            y += 31
        draw.text((48, HEIGHT - 44), "MarTech Verify -> MarTech Change Guard",
                  font=mono, fill=colours["dim"])
        return image

    frames, durations = [], []
    prompt_style, prompt = transcript[0]
    for chars in range(0, len(prompt) + 1, 4):
        frames.append(render([(prompt_style, prompt[:chars] + ("_" if chars < len(prompt) else ""))]))
        durations.append(75)
    durations[-1] = 700
    for count in range(2, len(transcript) + 1):
        frames.append(render(transcript[:count]))
        durations.append(500 if transcript[count - 1][0] == "heading" else 330)
    durations[-1] = 6000
    return frames, durations


def write_gif(frames, durations, stamp):
    from PIL import Image
    palette = frames[-1].quantize(colors=64)
    encoded = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    encoded[0].save(GIF, save_all=True, append_images=encoded[1:], duration=durations,
                    loop=0, optimize=True, disposal=2, comment=stamp)


def write_mp4(frames, durations, stamp):
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError("MP4 generation requires imageio-ffmpeg") from exc
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo",
        "-pix_fmt", "rgb24", "-s", "%dx%d" % (WIDTH, HEIGHT), "-r", str(FPS),
        "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-metadata", "comment=" + stamp.decode("ascii"), str(MP4),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdin is not None
    for frame, duration in zip(frames, durations):
        for _ in range(max(1, round(duration / 1000 * FPS))):
            process.stdin.write(frame.tobytes())
    process.stdin.close()
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    if process.wait() != 0:
        raise RuntimeError("FFmpeg failed: %s" % stderr.strip())


def generate(verify_repo):
    data = capture(verify_repo)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    stamp = marker(data)
    frames, durations = render_frames(data)
    write_gif(frames, durations, stamp)
    write_mp4(frames, durations, stamp)
    print("wrote connected walkthrough GIF, MP4, and provenance")
    return check()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify-repo", type=pathlib.Path, default=ROOT.parent / "martech-verify")
    args = parser.parse_args(argv)
    try:
        return check() if args.check else generate(args.verify_repo)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print("could not build connected demo: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
