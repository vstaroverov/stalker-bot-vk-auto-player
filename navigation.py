"""
navigation.py — навигация бота по карте зон.

Navigator:
  - Самообучающийся граф переходов (BFS-маршруты)
  - Координатный компас как fallback для незнакомых зон
  - Anti-backtrack
  - Детекция кнопок движения
"""

from __future__ import annotations

import json
import os
from collections import deque


class Navigator:
    """Управляет навигацией бота по карте зон."""

    # Противоположные направления
    DIRECTION_OPPOSITES: dict[str, str] = {
        "северо-восток": "юго-запад",
        "северо-запад":  "юго-восток",
        "юго-восток":    "северо-запад",
        "юго-запад":     "северо-восток",
        "север": "юг",
        "юг":    "север",
        "восток": "запад",
        "запад":  "восток",
    }

    # Стрелочные эмодзи, характерные для кнопок движения
    _MOVE_ARROWS = frozenset("⬆⬇⬈⬉⬊⬋➡⬅↑↓←→")

    # Кнопки «К ...» которые НЕ являются переходами между зонами
    _NOT_ZONE_BUTTONS = frozenset({
        "к аномалии", "к костру", "к сидоровичу", "к торговцу",
        "к цели", "к хижине", "к лагерю",
    })

    # Единичные векторы направлений
    DIRECTION_VECTORS: dict[str, tuple[float, float]] = {
        "север":         ( 0.0,   1.0),
        "юг":            ( 0.0,  -1.0),
        "восток":        ( 1.0,   0.0),
        "запад":         (-1.0,   0.0),
        "северо-восток": ( 0.71,  0.71),
        "северо-запад":  (-0.71,  0.71),
        "юго-восток":    ( 0.71, -0.71),
        "юго-запад":     (-0.71, -0.71),
    }

    # Координатная карта зон. Начало: Деревня новичков (0, 0).
    # X: восток +, запад −.   Y: север +, юг −.
    ZONE_POSITIONS: dict[str, tuple[float, float]] = {

        # === ЦЕНТР / ДЕРЕВНЯ ===
        "деревня новичков":           ( 0.0,   0.0),
        "обочина дороги":             ( 1.0,   0.0),
        "дорога к деревне":           (-1.0,   0.0),
        "дорога на кпп":              ( 0.0,  -0.5),
        "высокая трава":              ( 1.5,   0.5),
        "обочина у дороги":           ( 1.0,   0.5),
        "костер у дороги":            (-1.5,   0.5),
        "каменистые холмы":           (-2.0,   0.5),
        "россыпь камней":             (-2.5,   0.5),

        # === СЕВЕР — СВАЛКА / ПЕРЕВАЛОЧНЫЙ ===
        "тоннель на болота":          ( 0.0,   1.0),
        "перевалочный пункт":         ( 0.0,   1.5),
        "смотровая вышка":            ( 0.0,   2.0),
        "свалка":                     ( 0.5,   2.0),
        "опасные склоны":             ( 1.0,   2.5),
        "тропа на свалку":            ( 1.0,   3.0),
        "снеговая башня":             ( 0.5,   3.0),

        # === СЕВЕРНЫЕ БОЛОТА ===
        "рыбацкий хутор":            (-0.5,   2.5),
        "старая церковь":            (-1.0,   3.0),
        "лодочная станция":          (-1.5,   3.0),
        "сорвавшийся хутор":         (-1.5,   3.5),
        "насосная станция":          (-1.0,   4.0),

        # === КРАЙНИЙ СЕВЕР ===
        "старое кпп на севере":       ( 0.0,   5.0),
        "рыскни земли":               ( 0.5,   5.0),
        "рыхлые земли":               ( 0.5,   5.0),  # альт. написание
        "лагерь упорствующих":        ( 0.0,   5.5),

        # === СЕВЕРО-ЗАПАД — РОЩИ, ЛОЩИНА ===
        "опасная роща":              (-2.0,   1.0),
        "темная тернистая роща":     (-2.5,   1.0),
        "тёмная тернистая роща":     (-2.5,   1.0),
        "тернистая роща":            (-2.5,   1.0),
        "лощина":                    (-2.0,   1.5),
        "яма":                       (-2.5,   1.5),
        "заросшая роща":             (-2.0,   2.0),
        "роща с деревом желаний":    (-2.5,   2.0),
        "хижина":                    (-3.0,   1.0),
        "загрязнённая роща":         (-3.0,   0.5),
        "загрязненная роща":         (-3.0,   0.5),

        # === СЕВЕРО-ВОСТОК ===
        "элеватор":                   ( 2.0,   1.5),
        "туннель в темную долину":    ( 1.5,   1.5),
        "холмы":                      ( 2.5,   1.5),
        "тоннель под мостом":         ( 2.0,   2.0),
        "туннель под мостом":         ( 2.0,   2.0),
        "опасные окопы":              ( 3.0,   2.0),

        # === ЮГ / КПП ===
        "кпп с д-3":                  ( 0.0,  -2.0),
        "кпп с д3":                   ( 0.0,  -2.0),
        "засада у кпп":               ( 0.5,  -2.0),
        "вход в болотистые сопки":    ( 0.0,  -3.0),
        "болотистые сопки":           ( 0.0,  -3.0),
        "тайная выходящая дорога":    ( 0.5,  -3.0),

        # === ЮЖНЫЕ БОЛОТА ===
        "средние болота":             ( 0.0,  -4.0),
        "скорая серая":               ( 0.5,  -4.0),
        "сердце болота":              ( 0.0,  -5.0),

        # === СПЕЦИАЛЬНЫЕ (записки, цели) ===
        "роща у деревни новичков":    (-1.0,   0.5),
        "роща у деревни":             (-1.0,   0.5),
        "дорога у деревни":           (-0.5,   0.0),
        "обломки у дороги":           ( 0.5,  -0.5),
        "туннель на болото":          ( 0.0,   1.0),  # альт. написание
    }

    # -------------------------------------------------------------------------

    def __init__(self, graph_file: str):
        self._graph_file = graph_file
        self.current_zone:  str        = ""
        self.reverse_dir:   str | None = None
        self.visited_zones: list[str]  = []
        self.prev_zone:     str | None = None
        self.prev_direction: str | None = None
        self._graph: dict[str, dict[str, str]] = {}
        self._load_graph()

    # --- Граф переходов ---

    def _load_graph(self) -> None:
        if os.path.exists(self._graph_file):
            with open(self._graph_file, encoding="utf-8") as f:
                self._graph = json.load(f)

    def _save_graph(self) -> None:
        with open(self._graph_file, "w", encoding="utf-8") as f:
            json.dump(self._graph, f, ensure_ascii=False, indent=2)

    def record_transition(self, from_zone: str, direction_key: str, to_zone: str) -> bool:
        """
        Записывает переход в граф (двунаправленно).
        Возвращает True если граф обновлён и сохранён.
        """
        if not from_zone or not to_zone or from_zone == to_zone:
            return False
        updated = False
        if from_zone not in self._graph:
            self._graph[from_zone] = {}
        if self._graph[from_zone].get(direction_key) != to_zone:
            self._graph[from_zone][direction_key] = to_zone
            updated = True
        opp = self.DIRECTION_OPPOSITES.get(direction_key)
        if opp:
            if to_zone not in self._graph:
                self._graph[to_zone] = {}
            if self._graph[to_zone].get(opp) != from_zone:
                self._graph[to_zone][opp] = from_zone
                updated = True
        if updated:
            self._save_graph()
        return updated

    # --- Текущая позиция ---

    def update_location(self, new_zone: str) -> tuple[bool, tuple[str, str, str] | None]:
        """
        Обновляет текущую зону.
        Возвращает (zone_changed, recorded_transition | None).
        recorded_transition = (from_zone, direction_key, to_zone) если граф обновлён.
        """
        if not new_zone or new_zone == self.current_zone:
            return False, None
        transition: tuple[str, str, str] | None = None
        if self.prev_zone and self.prev_direction:
            updated = self.record_transition(self.prev_zone, self.prev_direction, new_zone)
            if updated:
                transition = (self.prev_zone, self.prev_direction, new_zone)
            self.prev_zone = None
            self.prev_direction = None
        self.current_zone = new_zone
        if new_zone not in self.visited_zones:
            self.visited_zones.append(new_zone)
        return True, transition

    def reset(self) -> None:
        """Сбрасывает навигационное состояние (новая цель / охота выключена)."""
        self.reverse_dir    = None
        self.visited_zones  = []
        self.prev_zone      = None
        self.prev_direction = None

    def visited_context(self, limit: int = 8) -> list[str]:
        """Последние посещённые зоны, кроме текущей."""
        return [z for z in self.visited_zones if z != self.current_zone][-limit:]

    # --- Кнопки движения ---

    def get_direction_key(self, label: str) -> str | None:
        """Извлекает ключ направления из метки кнопки ('⬆ На север' → 'север')."""
        label_low = label.lower()
        for direction in sorted(self.DIRECTION_OPPOSITES, key=len, reverse=True):
            if direction in label_low:
                return direction
        return None

    def is_movement_button(self, label: str) -> bool:
        """True если кнопка — переход между зонами карты."""
        if self.get_direction_key(label) is not None:
            return True
        if any(ch in label for ch in self._MOVE_ARROWS):
            return True
        label_low = label.lower().strip()
        if label_low in self._NOT_ZONE_BUTTONS:
            return False
        if label_low.startswith("к ") and len(label_low) > 2:
            return True
        return False

    def movement_buttons(self, buttons: list) -> list:
        """Возвращает только кнопки перемещения между зонами."""
        return [b for b in buttons if self.is_movement_button(b["label"])]

    def filter_backtrack(self, nav_buttons: list) -> list:
        """Убирает кнопку возврата назад (anti-backtrack), если останется ≥1 кнопка."""
        if not self.reverse_dir or len(nav_buttons) <= 1:
            return nav_buttons
        forward = [b for b in nav_buttons
                   if self.reverse_dir not in b["label"].lower()]
        return forward if forward else nav_buttons

    # --- BFS-маршрут по известному графу ---

    def _zone_matches(self, zone: str, target: str) -> bool:
        """Точное совпадение или стем-матчинг (устойчивость к склонениям)."""
        z, t = zone.lower(), target.lower()
        if z == t:
            return True
        words = [w for w in t.split() if len(w) >= 4]
        if not words:
            return False
        stems = [w[:max(3, len(w) - 2)] for w in words]
        return all(s in z for s in stems)

    def find_path(self, target: str) -> list[str] | None:
        """
        BFS по известному графу переходов.
        Возвращает список направлений от current_zone до target или None.
        """
        current = self.current_zone
        if not current or not self._graph:
            return None
        if self._zone_matches(current, target):
            return []
        queue: deque[tuple[str, list[str]]] = deque([(current, [])])
        visited: set[str] = {current}
        while queue:
            node, path = queue.popleft()
            for direction, next_zone in self._graph.get(node, {}).items():
                if self._zone_matches(next_zone, target):
                    return path + [direction]
                if next_zone not in visited:
                    visited.add(next_zone)
                    queue.append((next_zone, path + [direction]))
        return None

    # --- Компасная навигация по координатам ---

    def _get_zone_position(self, zone: str) -> tuple[float, float] | None:
        """Координаты зоны с учётом стем-матчинга."""
        zl = zone.lower().strip()
        if zl in self.ZONE_POSITIONS:
            return self.ZONE_POSITIONS[zl]
        words = [w for w in zl.split() if len(w) >= 4]
        if not words:
            return None
        stems = [w[:max(3, len(w) - 2)] for w in words]
        best_key, best_count = None, 0
        for key in self.ZONE_POSITIONS:
            count = sum(1 for s in stems if s in key)
            if count > best_count:
                best_count, best_key = count, key
        return self.ZONE_POSITIONS[best_key] if best_key and best_count > 0 else None

    def suggest_direction(self, target: str) -> str | None:
        """Оптимальное направление к target по координатам."""
        cp = self._get_zone_position(self.current_zone)
        tp = self._get_zone_position(target)
        if cp is None or tp is None:
            return None
        dx, dy = tp[0] - cp[0], tp[1] - cp[1]
        if abs(dx) < 0.2 and abs(dy) < 0.2:
            return None  # зоны практически рядом
        best_dir, best_score = None, -999.0
        for dir_name, (vx, vy) in self.DIRECTION_VECTORS.items():
            score = vx * dx + vy * dy
            if score > best_score:
                best_score, best_dir = score, dir_name
        return best_dir

    def best_direction_button(self, buttons: list, target_dir: str) -> tuple[str, str] | None:
        """
        Кнопка с наибольшим dot-product к target_dir.
        Возвращает (label, direction_key) или None.
        """
        tv = self.DIRECTION_VECTORS.get(target_dir)
        if tv is None:
            return None
        best_btn, best_dir_key, best_score = None, None, -999.0
        for b in buttons:
            dk = self.get_direction_key(b["label"])
            if dk is None:
                continue
            bv = self.DIRECTION_VECTORS.get(dk)
            if bv is None:
                continue
            score = tv[0] * bv[0] + tv[1] * bv[1]
            if score > best_score:
                best_score, best_btn, best_dir_key = score, b["label"], dk
        return (best_btn, best_dir_key) if best_btn else None

    def compass_hint(self, target: str) -> str:
        """Человекочитаемая строка с подсказкой для лога."""
        cp = self._get_zone_position(self.current_zone)
        tp = self._get_zone_position(target)
        if cp is None:
            return f"(«{self.current_zone}» не на карте)"
        if tp is None:
            return f"(«{target}» не на карте)"
        d   = self.suggest_direction(target)
        dx  = tp[0] - cp[0]
        dy  = tp[1] - cp[1]
        dist = (dx ** 2 + dy ** 2) ** 0.5
        return f"«{self.current_zone}»→«{target}»: Δ({dx:+.1f},{dy:+.1f}) ≈{dist:.1f} → {d}"

    # --- Выбор следующего хода ---

    def choose_move(
        self,
        nav_buttons: list,
        target: str,
    ) -> tuple[str, str, str] | None:
        """
        Выбирает следующую кнопку движения к target.
        1. BFS по известному графу
        2. Компас как fallback

        Возвращает (label, direction_key, method) или None.
        method: "bfs" | "compass"
        """
        # 1. BFS
        path = self.find_path(target)
        if path:
            next_dir = path[0]
            bfs_btn = next(
                (b["label"] for b in nav_buttons
                 if self.get_direction_key(b["label"]) == next_dir),
                None,
            )
            if bfs_btn:
                return bfs_btn, next_dir, "bfs"

        # 2. Компас
        comp_dir = self.suggest_direction(target)
        if comp_dir:
            best = self.best_direction_button(nav_buttons, comp_dir)
            if best:
                btn_label, btn_dir = best
                return btn_label, btn_dir, "compass"

        return None

    def record_moved(self, direction_key: str) -> None:
        """Запоминает выбранное направление — будет записано в граф при смене зоны."""
        self.prev_zone      = self.current_zone
        self.prev_direction = direction_key
        self.reverse_dir    = self.DIRECTION_OPPOSITES.get(direction_key)

    # --- Верификация покрытия карты ---

    def verify_coverage(self) -> dict:
        """
        Проверяет что компас может предложить направление между любой парой зон
        в ZONE_POSITIONS. Возвращает статистику.
        """
        zones = list(self.ZONE_POSITIONS.keys())
        # Дедупликация по позиции (несколько ключей → одни координаты)
        unique: dict[tuple, str] = {}
        for z in zones:
            pos = self.ZONE_POSITIONS[z]
            if pos not in unique:
                unique[pos] = z
        unique_zones = list(unique.values())

        orig = self.current_zone
        reachable = 0
        blind_pairs: list[tuple[str, str]] = []
        for from_z in unique_zones:
            self.current_zone = from_z
            for to_z in unique_zones:
                if from_z == to_z:
                    continue
                if self.suggest_direction(to_z) is not None:
                    reachable += 1
                else:
                    blind_pairs.append((from_z, to_z))
        self.current_zone = orig
        total = len(unique_zones) * (len(unique_zones) - 1)
        return {
            "unique_zones":  len(unique_zones),
            "total_pairs":   total,
            "reachable":     reachable,
            "blind_pairs":   blind_pairs,
            "coverage_pct":  round(reachable / total * 100, 1) if total else 0,
        }
