import argparse
import math
from pathlib import Path
from xml.etree import ElementTree


def render_badge(report: Path) -> str:
    root = ElementTree.parse(report).getroot()
    if root.tag != "coverage":
        raise ValueError("Expected a Cobertura coverage report")
    rate = float(root.attrib["line-rate"])
    if not math.isfinite(rate) or not 0 <= rate <= 1:
        raise ValueError("Coverage line-rate must be between zero and one")

    percentage = rate * 100
    color = "#4c1" if percentage >= 90 else "#97ca00" if percentage >= 80 else "#dfb317"
    value = f"{percentage:.1f}%"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="174" height="20" '
        f'role="img" aria-label="Python coverage: {value}">\n'
        f"  <title>Python coverage: {value}</title>\n"
        '  <rect width="174" height="20" rx="3" fill="#555"/>\n'
        f'  <path fill="{color}" d="M118 0h53a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3h-53z"/>\n'
        '  <g fill="#fff" text-anchor="middle" '
        'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">\n'
        '    <text x="59" y="14">Python coverage</text>\n'
        f'    <text x="146" y="14">{value}</text>\n'
        "  </g>\n"
        "</svg>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an SVG badge from Python line coverage.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        badge = render_badge(args.input)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(badge, encoding="utf-8")
    except (OSError, ValueError, KeyError, ElementTree.ParseError) as exc:
        raise SystemExit(f"Coverage badge generation failed: {exc}") from None


if __name__ == "__main__":
    main()
