#!/usr/bin/env python3

from __future__ import annotations

import argparse
import random
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PALETTE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
BACKGROUND = "#0d1117"
ANT_COLOR = "#ff7b72"


@dataclass
class Cell:
    x: int
    y: int
    level: int


class ContributionCellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: list[Cell] = []
        self._id_pattern = re.compile(r"^contribution-day-component-(\d)-(\d+)$")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "td":
            return

        attrs_map = {k: (v or "") for k, v in attrs}
        classes = attrs_map.get("class", "")
        if "ContributionCalendar-day" not in classes:
            return

        level_raw = attrs_map.get("data-level")
        cell_id = attrs_map.get("id", "")
        match = self._id_pattern.match(cell_id)

        if level_raw is None or not match:
            return

        y = int(match.group(1))
        x = int(match.group(2))
        level = int(level_raw)
        self.cells.append(Cell(x=x, y=y, level=max(0, min(4, level))))


def fetch_contribution_grid(username: str) -> list[list[int]]:
    url = f"https://github.com/users/{username}/contributions"
    req = urllib.request.Request(url, headers={"User-Agent": "contribution-life-gif"})

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc.reason}") from exc

    parser = ContributionCellParser()
    parser.feed(html)

    if not parser.cells:
        raise RuntimeError(
            "No contribution cells found. GitHub markup may have changed or user is invalid."
        )

    width = max(c.x for c in parser.cells) + 1
    height = 7
    grid = [[0 for _ in range(width)] for _ in range(height)]

    for cell in parser.cells:
        if 0 <= cell.y < height and 0 <= cell.x < width:
            grid[cell.y][cell.x] = cell.level

    return grid


def find_ant_start(grid: list[list[int]]) -> tuple[int, int]:
    height = len(grid)
    width = len(grid[0])
    return random.randrange(width), random.randrange(height)


def step_ant(
    grid: list[list[int]],
    ant_x: int,
    ant_y: int,
    direction: int,
) -> tuple[int, int, int]:
    height = len(grid)
    width = len(grid[0])

    # Generalized Langton's Ant for 5 GitHub levels.
    # Level decides turn direction, then level cycles to the next color.
    # 0..4 => Right, Left, Right, Left, Right
    turns = (1, -1, 1, -1, 1)

    current_level = grid[ant_y][ant_x]
    turn = turns[current_level]
    direction = (direction + turn) % 4
    grid[ant_y][ant_x] = (current_level + 1) % len(PALETTE)

    if direction == 0:  # up
        ant_y = (ant_y - 1) % height
    elif direction == 1:  # right
        ant_x = (ant_x + 1) % width
    elif direction == 2:  # down
        ant_y = (ant_y + 1) % height
    else:  # left
        ant_x = (ant_x - 1) % width

    return ant_x, ant_y, direction


def render_frame(
    grid: list[list[int]],
    *,
    cell_size: int,
    gap: int,
    margin: int,
    ant_position: tuple[int, int] | None,
) -> object:
    try:
        import importlib

        image_module = importlib.import_module("PIL.Image")
        draw_module = importlib.import_module("PIL.ImageDraw")
        Image = image_module.Image
        new_image = image_module.new
        ImageDraw = draw_module
    except ModuleNotFoundError as exc:
        raise SystemExit("Missing dependency: pillow. Install with `python -m pip install pillow`.") from exc

    rows = len(grid)
    cols = len(grid[0])
    width = margin * 2 + cols * cell_size + (cols - 1) * gap
    height = margin * 2 + rows * cell_size + (rows - 1) * gap

    image = new_image("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    radius = max(2, int(cell_size * 0.2))

    for y, row in enumerate(grid):
        for x, value in enumerate(row):
            px = margin + x * (cell_size + gap)
            py = margin + y * (cell_size + gap)
            color = PALETTE[max(0, min(4, value))]
            draw.rounded_rectangle(
                (px, py, px + cell_size - 1, py + cell_size - 1),
                radius=radius,
                fill=color,
            )

    if ant_position is not None:
        ant_x, ant_y = ant_position
        px = margin + ant_x * (cell_size + gap)
        py = margin + ant_y * (cell_size + gap)
        inset = max(2, cell_size // 4)
        draw.ellipse(
            (px + inset, py + inset, px + cell_size - 1 - inset, py + cell_size - 1 - inset),
            fill=ANT_COLOR,
        )

    return image


def generate_gif(
    username: str,
    output_path: Path,
    *,
    iterations: int,
    frame_duration_ms: int,
    cell_size: int,
    gap: int,
    margin: int,
) -> None:
    current = fetch_contribution_grid(username)
    frames: list[Any] = []
    ant_x, ant_y = find_ant_start(current)
    direction = 1

    frames.append(
        render_frame(
            current,
            cell_size=cell_size,
            gap=gap,
            margin=margin,
            ant_position=(ant_x, ant_y),
        )
    )
    for _ in range(iterations):
        ant_x, ant_y, direction = step_ant(current, ant_x, ant_y, direction)
        frames.append(
            render_frame(
                current,
                cell_size=cell_size,
                gap=gap,
                margin=margin,
                ant_position=(ant_x, ant_y),
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    first: Any
    first, *rest = frames
    first.save(
        output_path,
        save_all=True,
        append_images=rest,
        optimize=True,
        duration=frame_duration_ms,
        loop=0,
        disposal=2,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Langton's Ant GIF from GitHub contributions"
    )
    parser.add_argument("--user", required=True, help="GitHub username")
    parser.add_argument(
        "--output",
        default="dist/github-contribution-life.gif",
        help="Output GIF path",
    )
    parser.add_argument("--iterations", type=int, default=900)
    parser.add_argument("--frame-duration-ms", type=int, default=35)
    parser.add_argument("--cell-size", type=int, default=12)
    parser.add_argument("--gap", type=int, default=3)
    parser.add_argument("--margin", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be >= 1")

    generate_gif(
        args.user,
        Path(args.output),
        iterations=args.iterations,
        frame_duration_ms=args.frame_duration_ms,
        cell_size=args.cell_size,
        gap=args.gap,
        margin=args.margin,
    )
    print(f"Generated {args.output}")


if __name__ == "__main__":
    main()
