#!/usr/bin/env python3

from __future__ import annotations

import argparse
import random
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from math import ceil
from pathlib import Path
from typing import Any


PALETTE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
BACKGROUND = "#0d1117"
SHIP_COLOR = "#58a6ff"
BULLET_COLOR = "#ff7b72"


@dataclass
class Cell:
    x: int
    y: int
    level: int


@dataclass
class Bullet:
    x: int
    y: int


class ContributionCellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: list[Cell] = []
        self._id_pattern = re.compile(r"^contribution-day-component-(\d)-(\d+)$")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "td":
            return

        attrs_map = {k: (v or "") for k, v in attrs}
        if "ContributionCalendar-day" not in attrs_map.get("class", ""):
            return

        level_raw = attrs_map.get("data-level")
        cell_id = attrs_map.get("id", "")
        match = self._id_pattern.match(cell_id)
        if level_raw is None or not match:
            return

        self.cells.append(
            Cell(
                x=int(match.group(2)),
                y=int(match.group(1)),
                level=max(0, min(4, int(level_raw))),
            )
        )


def fetch_contribution_grid(username: str) -> list[list[int]]:
    url = f"https://github.com/users/{username}/contributions"
    req = urllib.request.Request(
        url, headers={"User-Agent": "contribution-invaders-gif"}
    )

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
            "No contribution cells found. GitHub markup may have changed."
        )

    width = max(c.x for c in parser.cells) + 1
    height = 7
    grid = [[0 for _ in range(width)] for _ in range(height)]
    for cell in parser.cells:
        grid[cell.y][cell.x] = cell.level
    return grid


def build_enemies(contribution_grid: list[list[int]]) -> dict[tuple[int, int], int]:
    return {
        (x, y): level
        for y, row in enumerate(contribution_grid)
        for x, level in enumerate(row)
        if level > 0
    }


def enemy_bounds(enemies: dict[tuple[int, int], int]) -> tuple[int, int, int, int]:
    xs = [x for (x, _), hp in enemies.items() if hp > 0]
    ys = [y for (_, y), hp in enemies.items() if hp > 0]
    return min(xs), max(xs), min(ys), max(ys)


def pick_target_column(
    enemies: dict[tuple[int, int], int],
    formation_x: int,
    formation_y: int,
    ship_x: int,
) -> int:
    candidates = [
        (formation_x + ex, formation_y + ey, hp)
        for (ex, ey), hp in enemies.items()
        if hp > 0
    ]
    target_x, _, _ = max(candidates, key=lambda e: (e[1], -abs(e[0] - ship_x), e[2]))
    return target_x


def move_ship_towards(ship_x: int, target_x: int, width: int) -> int:
    if target_x > ship_x:
        return min(width - 1, ship_x + 1)
    if target_x < ship_x:
        return max(0, ship_x - 1)
    return ship_x


def move_bullets_and_apply_hits(
    bullets: list[Bullet],
    enemies: dict[tuple[int, int], int],
    formation_x: int,
    formation_y: int,
    bullet_speed: int,
) -> list[Bullet]:
    next_bullets: list[Bullet] = []

    for bullet in bullets:
        destroyed = False
        for _ in range(bullet_speed):
            bullet.y -= 1
            if bullet.y < 0:
                destroyed = True
                break

            rel = (bullet.x - formation_x, bullet.y - formation_y)
            if rel in enemies and enemies[rel] > 0:
                enemies[rel] -= 1
                if enemies[rel] <= 0:
                    del enemies[rel]
                destroyed = True
                break

        if not destroyed:
            next_bullets.append(bullet)

    return next_bullets


def step_enemy_formation(
    enemies: dict[tuple[int, int], int],
    width: int,
    formation_x: int,
    formation_y: int,
    direction: int,
) -> tuple[int, int, int]:
    if not enemies:
        return formation_x, formation_y, direction

    min_x, max_x, _, _ = enemy_bounds(enemies)
    if formation_x + max_x + direction >= width or formation_x + min_x + direction < 0:
        direction *= -1
        formation_y += 1
    else:
        formation_x += direction

    return formation_x, formation_y, direction


def compute_enemy_move_interval(total_hp: int, width: int, max_descents: int) -> int:
    estimated_ticks_to_clear = int(total_hp * 1.3 + width * 6)
    raw = ceil(estimated_ticks_to_clear / max(1, width * max_descents))
    return max(28, min(180, raw))


def render_frame(
    width_cells: int,
    height_cells: int,
    enemies: dict[tuple[int, int], int],
    formation_x: int,
    formation_y: int,
    bullets: list[Bullet],
    ship_x: int,
    ship_y: int,
    *,
    cell_size: int,
    gap: int,
    margin: int,
) -> object:
    try:
        import importlib

        image_module = importlib.import_module("PIL.Image")
        draw_module = importlib.import_module("PIL.ImageDraw")
        new_image = image_module.new
        image_draw = draw_module
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency: pillow. Install with `python -m pip install pillow`."
        ) from exc

    width_px = margin * 2 + width_cells * cell_size + (width_cells - 1) * gap
    height_px = margin * 2 + height_cells * cell_size + (height_cells - 1) * gap

    image = new_image("RGB", (width_px, height_px), BACKGROUND)
    draw = image_draw.Draw(image)
    radius = max(2, int(cell_size * 0.22))

    for (ex, ey), hp in enemies.items():
        x = formation_x + ex
        y = formation_y + ey
        px = margin + x * (cell_size + gap)
        py = margin + y * (cell_size + gap)
        draw.rounded_rectangle(
            (px, py, px + cell_size - 1, py + cell_size - 1),
            radius=radius,
            fill=PALETTE[max(1, min(4, hp))],
        )

    for bullet in bullets:
        px = margin + bullet.x * (cell_size + gap)
        py = margin + bullet.y * (cell_size + gap)
        bw = max(2, cell_size // 4)
        bh = max(4, int(cell_size * 0.55))
        cx = px + (cell_size - bw) // 2
        cy = py + (cell_size - bh) // 2
        draw.rounded_rectangle(
            (cx, cy, cx + bw - 1, cy + bh - 1), radius=2, fill=BULLET_COLOR
        )

    ship_px = margin + ship_x * (cell_size + gap)
    ship_py = margin + ship_y * (cell_size + gap)
    inset = max(1, cell_size // 8)
    draw.polygon(
        (
            ship_px + cell_size // 2,
            ship_py + inset,
            ship_px + cell_size - 1 - inset,
            ship_py + cell_size - 1 - inset,
            ship_px + inset,
            ship_py + cell_size - 1 - inset,
        ),
        fill=SHIP_COLOR,
    )

    return image


def generate_gif(
    username: str,
    output_path: Path,
    *,
    max_ticks: int,
    frame_duration_ms: int,
    cell_size: int,
    gap: int,
    margin: int,
    render_every: int,
    final_hold_frames: int,
) -> None:
    contribution_grid = fetch_contribution_grid(username)
    enemies = build_enemies(contribution_grid)
    if not enemies:
        raise RuntimeError("No enemies found. No contributions available to render.")

    contribution_width = len(contribution_grid[0])
    width = contribution_width + 2
    enemy_height = len(contribution_grid)
    height = enemy_height + 30
    ship_x = width // 2
    ship_y = height - 2

    formation_x = 1
    formation_y = 2
    enemy_direction = 1

    bullets: list[Bullet] = []
    cooldown = 0
    fire_cooldown_ticks = 0
    bullet_speed = 2

    total_hp = sum(enemies.values())
    max_descents_before_fail = max(3, ship_y - (formation_y + enemy_height) - 2)
    enemy_move_interval = compute_enemy_move_interval(
        total_hp, width, max_descents_before_fail
    )

    tick = 0
    current_target_x = ship_x
    frames: list[Any] = []
    frames.append(
        render_frame(
            width,
            height,
            enemies,
            formation_x,
            formation_y,
            bullets,
            ship_x,
            ship_y,
            cell_size=cell_size,
            gap=gap,
            margin=margin,
        )
    )

    while enemies and tick < max_ticks:
        tick += 1

        enemy_count = len(enemies)
        chaos_mode = enemy_count > 220

        if chaos_mode:
            if tick % 8 == 0 or ship_x == current_target_x:
                enemy_columns = sorted(
                    {formation_x + ex for (ex, _), hp in enemies.items() if hp > 0}
                )
                if enemy_columns:
                    if random.random() < 0.45:
                        nearest_columns = sorted(
                            enemy_columns, key=lambda col: abs(col - ship_x)
                        )[:12]
                        current_target_x = random.choice(nearest_columns)
                    else:
                        current_target_x = pick_target_column(
                            enemies, formation_x, formation_y, ship_x
                        )
        else:
            current_target_x = pick_target_column(
                enemies, formation_x, formation_y, ship_x
            )

        ship_x = move_ship_towards(ship_x, current_target_x, width)

        if cooldown <= 0:
            has_enemy_ahead = any(
                formation_x + ex == ship_x and formation_y + ey < ship_y
                for (ex, ey), hp in enemies.items()
                if hp > 0
            )
            if has_enemy_ahead:
                bullets.append(Bullet(x=ship_x, y=ship_y - 1))
                cooldown = fire_cooldown_ticks
        else:
            cooldown -= 1

        bullets = move_bullets_and_apply_hits(
            bullets, enemies, formation_x, formation_y, bullet_speed
        )

        if tick % enemy_move_interval == 0 and enemies:
            formation_x, formation_y, enemy_direction = step_enemy_formation(
                enemies,
                width,
                formation_x,
                formation_y,
                enemy_direction,
            )

        if tick % render_every == 0 or not enemies:
            frames.append(
                render_frame(
                    width,
                    height,
                    enemies,
                    formation_x,
                    formation_y,
                    bullets,
                    ship_x,
                    ship_y,
                    cell_size=cell_size,
                    gap=gap,
                    margin=margin,
                )
            )

    if frames:
        for _ in range(final_hold_frames):
            frames.append(frames[-1].copy())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    first, *rest = frames
    first.save(
        output_path,
        save_all=True,
        append_images=rest,
        optimize=False,
        duration=frame_duration_ms,
        loop=0,
        disposal=2,
    )

    if enemies:
        print(f"Generated {output_path} (stopped with {len(enemies)} enemies left)")
    else:
        print(f"Generated {output_path} (all enemies cleared in {tick} frames)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a self-playing Space Invaders GIF from GitHub contributions"
    )
    parser.add_argument("--user", required=True, help="GitHub username")
    parser.add_argument(
        "--output", default="dist/github-contribution.gif", help="Output GIF path"
    )
    parser.add_argument(
        "--iterations", type=int, default=6000, help="Maximum simulation ticks"
    )
    parser.add_argument("--frame-duration-ms", type=int, default=30)
    parser.add_argument("--render-every", type=int, default=1)
    parser.add_argument("--final-hold-frames", type=int, default=6)
    parser.add_argument("--cell-size", type=int, default=8)
    parser.add_argument("--gap", type=int, default=2)
    parser.add_argument("--margin", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be >= 1")
    if args.render_every < 1:
        raise SystemExit("--render-every must be >= 1")
    if args.final_hold_frames < 0:
        raise SystemExit("--final-hold-frames must be >= 0")

    generate_gif(
        args.user,
        Path(args.output),
        max_ticks=args.iterations,
        frame_duration_ms=args.frame_duration_ms,
        cell_size=args.cell_size,
        gap=args.gap,
        margin=args.margin,
        render_every=args.render_every,
        final_hold_frames=args.final_hold_frames,
    )


if __name__ == "__main__":
    main()
