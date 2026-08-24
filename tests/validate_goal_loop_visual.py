from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN = ROOT / "GOAL_LOOP.md"
CYCLE_SVG = ROOT / "assets" / "goal-loop-cycle.svg"
STATES_SVG = ROOT / "assets" / "goal-loop-states.svg"
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}

MIN_FONT_UNITS = 38.0
NARROW_WIDTH_PX = 360.0
MIN_READABLE_PX = 11.0


def number(node: ET.Element, name: str) -> float:
    return float(node.attrib[name])


def check_frame(path: Path) -> tuple[ET.Element, list[float], float]:
    root = ET.parse(path).getroot()
    view_box = [float(value) for value in root.attrib["viewBox"].split()]
    assert view_box == [0.0, 0.0, 1200.0, 700.0], f"{path.name}: viewBox must be 1200x700"
    assert view_box[2] > view_box[3], f"{path.name}: must be horizontal"

    font_sizes = [
        float(text.attrib["font-size"])
        for text in root.findall(".//svg:text", SVG_NS)
        if "font-size" in text.attrib
    ]
    assert font_sizes, f"{path.name}: no sized text"
    smallest = min(font_sizes)
    assert smallest >= MIN_FONT_UNITS, f"{path.name}: min font {smallest} < {MIN_FONT_UNITS}"
    narrow_px = smallest * (NARROW_WIDTH_PX / view_box[2])
    assert narrow_px >= MIN_READABLE_PX, f"{path.name}: {narrow_px:.1f}px at {NARROW_WIDTH_PX}px wide"
    return root, view_box, narrow_px


def main() -> None:
    markdown = MARKDOWN.read_text(encoding="utf-8")
    assert "PC幅では**横長・左から右**" in markdown
    assert "assets/goal-loop-cycle.svg" in markdown
    assert "assets/goal-loop-states.svg" in markdown
    assert "レスポンシブHTMLは520px以下" in markdown

    cycle, _, cycle_px = check_frame(CYCLE_SVG)
    nodes = {
        name: cycle.find(f".//svg:rect[@id='{name}-node']", SVG_NS)
        for name in ("done", "bottleneck", "next", "writeback", "continue")
    }
    missing = [name for name, node in nodes.items() if node is None]
    assert not missing, f"missing nodes: {missing}"
    done, bottleneck, next_node = nodes["done"], nodes["bottleneck"], nodes["next"]
    assert cycle.find(".//svg:path[@id='loop-arrow']", SVG_NS) is not None

    text_content = " ".join("".join(n.itertext()) for n in cycle.findall(".//svg:text", SVG_NS))
    for phrase in ("DoD未達", "AI安全作業", "CONTINUE", "旧値 → 新値"):
        assert phrase in text_content, f"cycle svg missing phrase: {phrase}"

    assert number(done, "x") < number(bottleneck, "x") < number(next_node, "x")
    bottleneck_area = number(bottleneck, "width") * number(bottleneck, "height")
    for other in ("done", "next", "writeback"):
        node = nodes[other]
        assert bottleneck_area > number(node, "width") * number(node, "height"), (
            f"bottleneck must be larger than {other}"
        )

    states, _, states_px = check_frame(STATES_SVG)
    states_text = " ".join("".join(n.itertext()) for n in states.findall(".//svg:text", SVG_NS))
    for phrase in ("CONTINUE", "REPLAN", "RECOVER", "DONE", "HANDOFF", "HARD_BLOCK"):
        assert phrase in states_text, f"states svg missing state: {phrase}"

    print(
        "PASS: 2 figures horizontal 1200x700, "
        f"order=done->bottleneck->next, bottleneck_area={bottleneck_area:.0f}, "
        f"min_narrow_font=cycle {cycle_px:.1f}px / states {states_px:.1f}px"
    )


if __name__ == "__main__":
    main()
