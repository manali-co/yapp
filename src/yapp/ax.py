"""Spike: read an app's UI as text through the Accessibility API and let Jev pick a target.

Everything here is experimental; it exists to answer two questions on a real Mac:
how big and noisy the trees are, and how well Jev chooses from them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

INTERESTING = {
    "AXButton",
    "AXTextField",
    "AXTextArea",
    "AXSearchField",
    "AXLink",
    "AXTab",
    "AXRadioButton",
    "AXCheckBox",
    "AXPopUpButton",
    "AXMenuButton",
    "AXComboBox",
    "AXMenuItem",
    "AXMenuBarItem",
    "AXToolbar",
    "AXDisclosureTriangle",
    "AXSlider",
    "AXIncrementor",
}
MAX_NODES = 3000
MAX_SECONDS = 0.8
MOD_NAMES = {0: "⌘", 1: "⇧⌘", 2: "⌥⌘", 3: "⌥⇧⌘", 4: "⌃⌘", 8: "⌃⌥⌘", 12: "⌃⌥⌘"}


@dataclass(frozen=True)
class Target:
    key: str
    kind: str  # "menu" | "control"
    role: str
    label: str  # what a person would call it
    path: str  # "File › New Tab" for menus, window title for controls
    shortcut: str = ""
    ref: Any = None  # the AXUIElement, for pressing

    def describe(self) -> str:
        s = f"{self.kind}: {self.path}" if self.kind == "menu" else f"{self.role[2:]}: {self.label}"
        return f"{s} ({self.shortcut})" if self.shortcut else s


def _attr(el: Any, name: str) -> Any:
    from ApplicationServices import AXUIElementCopyAttributeValue

    err, value = AXUIElementCopyAttributeValue(el, name, None)
    return value if err == 0 else None


def app_element(name: str | None) -> tuple[Any, str]:
    from AppKit import NSWorkspace
    from ApplicationServices import AXUIElementCreateApplication

    ws = NSWorkspace.sharedWorkspace()
    app = None
    if name:
        for a in ws.runningApplications():
            if name.lower() in (a.localizedName() or "").lower():
                app = a
                break
    if app is None:
        app = ws.frontmostApplication()
    return AXUIElementCreateApplication(app.processIdentifier()), str(app.localizedName())


def menu_targets(app: Any) -> list[Target]:
    out: list[Target] = []
    bar = _attr(app, "AXMenuBar")
    if bar is None:
        return out

    def walk(el: Any, trail: list[str], depth: int) -> None:
        for child in _attr(el, "AXChildren") or []:
            role = _attr(child, "AXRole") or ""
            title = _attr(child, "AXTitle") or ""
            if role == "AXMenu":
                walk(child, trail, depth)
                continue
            if not title:
                continue
            kids = _attr(child, "AXChildren") or []
            if kids and depth < 3:
                walk(child, trail + [title], depth + 1)
            elif role == "AXMenuItem" and _attr(child, "AXEnabled") is not False:
                cmd = _attr(child, "AXMenuItemCmdChar") or ""
                mods = _attr(child, "AXMenuItemCmdModifiers")
                shortcut = f"{MOD_NAMES.get(int(mods or 0), '⌘')}{cmd}" if cmd else ""
                path = " › ".join(trail + [title])
                out.append(Target(f"m{len(out)}", "menu", role, title, path, shortcut, child))

    walk(bar, [], 0)
    return out


def control_targets(app: Any) -> tuple[list[Target], int]:
    out: list[Target] = []
    win = _attr(app, "AXFocusedWindow") or (_attr(app, "AXWindows") or [None])[0]
    if win is None:
        return out, 0
    title = _attr(win, "AXTitle") or ""
    seen = 0
    started = time.perf_counter()
    stack = [win]
    while stack and seen < MAX_NODES and time.perf_counter() - started < MAX_SECONDS:
        el = stack.pop()
        seen += 1
        role = _attr(el, "AXRole") or ""
        if role in INTERESTING and role not in ("AXToolbar", "AXMenuBarItem"):
            label = _attr(el, "AXTitle") or _attr(el, "AXDescription") or ""
            value = _attr(el, "AXValue")
            if isinstance(value, str) and value and len(value) < 60 and role.startswith("AXText"):
                label = f"{label} [{value}]" if label else value
            if label:
                out.append(Target(f"c{len(out)}", "control", role, str(label), title, "", el))
        stack.extend(_attr(el, "AXChildren") or [])
    return out, seen


def narrow(targets: list[Target], words: str, limit: int) -> list[Target]:
    def score(t: Target) -> float:
        return max(fuzz.token_set_ratio(words, t.label), fuzz.partial_ratio(words, t.path) * 0.9)

    return sorted(sorted(targets, key=lambda t: -score(t))[:limit], key=lambda t: t.key)


def ask_jev(words: str, targets: list[Target], model: str) -> dict[str, Any]:
    from typesafe_sdk import Choice, TypeSafeClient

    client = TypeSafeClient(model=model)
    criteria: dict[str, Any] = {t.key: t.describe() for t in targets}
    criteria["none"] = "Nothing on this screen or in these menus matches what the user asked"
    r = client.system_one(
        {"instruction": words},
        {
            "target": Choice(
                instructions="Which menu item or on-screen control does the user want?",
                criteria=criteria,
            ),
            "operation": Choice(
                instructions="What should be done with the chosen target?",
                criteria={
                    "press": "Click or activate it (buttons, menu items, links, tabs)",
                    "type": "Put the spoken text into it (text fields, search fields)",
                    "none": "Nothing",
                },
            ),
        },
    )
    tgt = r.choices["target"]
    op = r.choices["operation"]
    top = sorted(tgt.probabilities.items(), key=lambda kv: -kv[1])[:3]
    return {"choice": tgt.choice, "confidence": tgt.confidence, "top": top, "operation": op.choice}


def run_ax(app_name: str | None, phrases: list[str], model: str, out_path: str) -> int:
    with open(out_path, "a") as f:

        def p(line: str = "") -> None:
            f.write(line + "\n")
            f.flush()

        t0 = time.perf_counter()
        app, name = app_element(app_name)
        menus = menu_targets(app)
        controls, seen = control_targets(app)
        p(
            f"=== {name}: {len(menus)} menu items, {len(controls)} labelled controls "
            f"(walked {seen} nodes) in {(time.perf_counter() - t0) * 1000:.0f} ms ==="
        )
        for ph in phrases:
            cands = narrow(menus + controls, ph, 30)
            t1 = time.perf_counter()
            res = ask_jev(ph, cands, model)
            by = {t.key: t for t in cands}
            pick = by.get(res["choice"])
            p(
                f'\n"{ph}" -> {res["operation"]} {pick.describe() if pick else res["choice"]}  '
                f"conf={res['confidence']:.2f}  jev={(time.perf_counter() - t1) * 1000:.0f} ms"
            )
            for k, v in res["top"]:
                p(f"    {v:.2f}  {by[k].describe() if k in by else k}")
    return 0
