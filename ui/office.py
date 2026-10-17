from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from typing import Callable


STATE_LABELS = {
    "IDLE": "Livre",
    "READING": "Lendo",
    "RESEARCHING": "Pesquisando",
    "WRITING": "Redigindo",
    "REVIEWING": "Revisando",
    "WAITING": "Aguardando",
    "REVISING": "Corrigindo",
    "DONE": "Concluído",
    "ERROR": "Erro",
}


class OfficeCanvas(tk.Canvas):
    def __init__(self, master: tk.Misc, *, root: Path, on_agent_click: Callable[[str], None], **kwargs):
        self.palette = json.loads((root / "ui" / "sprites" / "palette.json").read_text(encoding="utf-8"))
        super().__init__(master, bg=self.palette["background"], highlightthickness=0, **kwargs)
        self.on_agent_click = on_agent_click
        self.agent_boxes: dict[str, tuple[int, int, int, int]] = {}
        self.states = {"estagiario": "IDLE", "junior": "IDLE", "senior": "IDLE"}
        self.activities = {"estagiario": "", "junior": "", "senior": ""}
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda _e: self.redraw())

    def _state_color(self, state: str) -> str:
        if state == "DONE":
            return self.palette["success"]
        if state == "ERROR":
            return self.palette["danger"]
        if state in {"READING", "RESEARCHING", "WRITING", "REVIEWING", "REVISING"}:
            return self.palette["accent"]
        if state == "WAITING":
            return self.palette["warning"]
        return self.palette["idle"]

    def update_agents(self, states: dict[str, str], activities: dict[str, str] | None = None) -> None:
        self.states.update(states)
        if activities:
            self.activities.update(activities)
        self.redraw()

    def _click(self, event: tk.Event) -> None:
        for agent, box in self.agent_boxes.items():
            x1, y1, x2, y2 = box
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.on_agent_click(agent)
                return

    def _desk(self, x: int, y: int, scale: int = 1) -> None:
        p = self.palette
        w, h = 126 * scale, 58 * scale
        self.create_rectangle(x, y, x + w, y + h, fill=p["desk"], outline=p["desk_edge"], width=3)
        self.create_rectangle(x + 44 * scale, y + 8 * scale, x + 82 * scale, y + 30 * scale, fill=p["monitor"], outline=p["wall"])
        self.create_rectangle(x + 49 * scale, y + 12 * scale, x + 77 * scale, y + 25 * scale, fill=p["monitor_screen"], outline="")
        self.create_rectangle(x + 61 * scale, y + 30 * scale, x + 66 * scale, y + 38 * scale, fill=p["monitor"], outline="")
        self.create_rectangle(x + 20 * scale, y + 14 * scale, x + 33 * scale, y + 24 * scale, fill=p["paper"], outline="")

    def _person(self, agent: str, x: int, y: int, label: str) -> None:
        p = self.palette
        state = self.states.get(agent, "IDLE")
        color = self._state_color(state)
        self.create_rectangle(x + 10, y, x + 30, y + 20, fill="#c59b77", outline=p["wall"])
        self.create_rectangle(x + 7, y + 20, x + 33, y + 46, fill=color, outline=p["wall"])
        self.create_rectangle(x, y + 22, x + 7, y + 40, fill=color, outline=p["wall"])
        self.create_rectangle(x + 33, y + 22, x + 40, y + 40, fill=color, outline=p["wall"])
        self.create_rectangle(x + 9, y + 46, x + 18, y + 58, fill="#20252c", outline=p["wall"])
        self.create_rectangle(x + 22, y + 46, x + 31, y + 58, fill="#20252c", outline=p["wall"])
        self.create_text(x + 20, y + 72, text=label, fill=p["text"], font=("TkFixedFont", 9, "bold"))
        status = STATE_LABELS.get(state, state)
        self.create_text(x + 20, y + 88, text=status, fill=color, font=("TkFixedFont", 8))
        activity = self.activities.get(agent, "")
        if activity:
            short = activity if len(activity) <= 34 else activity[:31] + "..."
            self.create_text(x + 20, y + 102, text=short, fill=p["muted"], font=("TkFixedFont", 7))
        self.agent_boxes[agent] = (x - 8, y - 8, x + 48, y + 110)

    def redraw(self) -> None:
        self.delete("all")
        self.agent_boxes.clear()
        p = self.palette
        w = max(self.winfo_width(), 760)
        h = max(self.winfo_height(), 520)

        self.create_rectangle(0, 0, w, h, fill=p["floor"], outline="")
        self.create_rectangle(0, 0, w, 44, fill=p["wall"], outline="")
        self.create_text(18, 22, anchor="w", text="PIXEL LEGAL OFFICE", fill=p["text"], font=("TkFixedFont", 13, "bold"))

        self.create_rectangle(26, 72, 165, 164, fill="#263441", outline=p["wall"], width=3)
        self.create_text(95, 88, text="QUADRO DE TAREFAS", fill=p["text"], font=("TkFixedFont", 8, "bold"))
        for i in range(3):
            self.create_rectangle(42, 104 + i * 16, 148, 113 + i * 16, fill=p["paper"], outline="")
        self.create_rectangle(w - 155, 70, w - 40, 198, fill="#3b322c", outline=p["wall"], width=3)
        for y in (96, 128, 160):
            self.create_rectangle(w - 146, y, w - 49, y + 6, fill=p["desk_edge"], outline="")
        for x in range(w - 137, w - 58, 16):
            self.create_rectangle(x, 103, x + 9, 126, fill="#6d7682", outline="")

        self._desk(215, 150)
        self._desk(430, 150)
        self.create_rectangle(w - 260, h - 210, w - 24, h - 24, fill="#252b33", outline=p["wall"], width=3)
        self.create_text(w - 142, h - 194, text="SALA SÊNIOR", fill=p["muted"], font=("TkFixedFont", 8, "bold"))
        self._desk(w - 215, h - 142)

        self._person("estagiario", 258, 238, "ESTAGIÁRIO")
        self._person("junior", 474, 238, "ADV. JÚNIOR")
        self._person("senior", w - 172, h - 118, "ADV. SÊNIOR")

        self.create_text(20, h - 18, anchor="w", text="Clique em um funcionário para abrir o painel e conversar.", fill=p["muted"], font=("TkFixedFont", 8))
