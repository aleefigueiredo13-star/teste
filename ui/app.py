from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from orchestrator.workflow import WorkflowEngine
from tools.filesystem import (
    attach_documents,
    create_case,
    create_task,
    list_tasks,
    load_task,
    project_root,
    read_events,
)
from ui.components.panels import AGENT_NAMES, format_employee_panel, format_task_panel
from ui.office import OfficeCanvas


class NewTaskDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, on_submit):
        super().__init__(master)
        self.title("Nova tarefa")
        self.geometry("650x610")
        self.transient(master)
        self.grab_set()
        self.on_submit = on_submit
        self.files: list[str] = []

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Processo").pack(anchor="w")
        self.process = ttk.Entry(outer)
        self.process.pack(fill="x", pady=(4, 12))

        ttk.Label(outer, text="Representamos").pack(anchor="w")
        self.rep = tk.StringVar(value="Reclamada")
        ttk.Combobox(outer, textvariable=self.rep, values=["Reclamante", "Reclamada", "Outro"], state="readonly").pack(fill="x", pady=(4, 12))

        ttk.Label(outer, text="Tarefa").pack(anchor="w")
        self.task = tk.Text(outer, height=8, wrap="word")
        self.task.pack(fill="both", pady=(4, 12))

        docs_row = ttk.Frame(outer)
        docs_row.pack(fill="x")
        ttk.Button(docs_row, text="Anexar arquivos", command=self._attach).pack(side="left")
        self.docs_label = ttk.Label(docs_row, text="Nenhum arquivo")
        self.docs_label.pack(side="left", padx=10)

        ttk.Separator(outer).pack(fill="x", pady=14)
        self.auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(outer, text="Orquestrador decide os agentes", variable=self.auto, command=self._toggle_agents).pack(anchor="w")

        self.agent_vars = {
            "estagiario": tk.BooleanVar(value=True),
            "junior": tk.BooleanVar(value=True),
            "senior": tk.BooleanVar(value=True),
        }
        self.agent_checks = []
        row = ttk.Frame(outer)
        row.pack(fill="x", pady=10)
        for agent in ("estagiario", "junior", "senior"):
            cb = ttk.Checkbutton(row, text=AGENT_NAMES[agent].title(), variable=self.agent_vars[agent])
            cb.pack(side="left", padx=(0, 14))
            self.agent_checks.append(cb)
        self._toggle_agents()

        ttk.Button(outer, text="DELEGAR AO ESCRITÓRIO", command=self._submit).pack(fill="x", pady=(18, 0))

    def _attach(self) -> None:
        selected = filedialog.askopenfilenames(
            title="Anexar documentos",
            filetypes=[("Documentos suportados", "*.pdf *.docx *.txt *.md"), ("Todos", "*.*")],
        )
        if selected:
            self.files = list(selected)
            self.docs_label.config(text=f"{len(self.files)} arquivo(s)")

    def _toggle_agents(self) -> None:
        state = "disabled" if self.auto.get() else "normal"
        for cb in self.agent_checks:
            cb.config(state=state)

    def _submit(self) -> None:
        process = self.process.get().strip()
        task = self.task.get("1.0", "end").strip()
        if not process:
            messagebox.showerror("Campo obrigatório", "Informe o número/identificador do processo.")
            return
        if not task:
            messagebox.showerror("Campo obrigatório", "Descreva a tarefa.")
            return
        selected_agents = [a for a, var in self.agent_vars.items() if var.get()]
        if not self.auto.get() and not selected_agents:
            messagebox.showerror("Agentes", "Selecione ao menos um agente ou habilite o orquestrador.")
            return
        self.on_submit({
            "process": process,
            "represented_as": self.rep.get(),
            "task": task,
            "files": self.files,
            "auto_orchestrator": self.auto.get(),
            "selected_agents": selected_agents,
        })
        self.destroy()


class PixelLegalOfficeApp(tk.Tk):
    def __init__(self, *, root_path: Path | None = None):
        super().__init__()
        self.root_path = root_path or project_root()
        self.engine = WorkflowEngine(root=self.root_path)
        self.title("Pixel Legal Office")
        self.geometry("1220x760")
        self.minsize(1050, 650)
        self.selected_agent = "senior"
        self.selected_task: dict | None = None
        self.chat_queue: queue.Queue = queue.Queue()

        self._build()
        self._refresh_tasks()
        self.after(600, self._poll)

    def _build(self) -> None:
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="NOVA TAREFA", command=self._new_task).pack(side="left")
        ttk.Button(toolbar, text="ABRIR PASTA", command=self._open_folder).pack(side="left", padx=8)
        ttk.Label(toolbar, text="Local-first · filesystem · Responses API", foreground="#666").pack(side="right")

        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(main)
        right = ttk.Frame(main, width=360)
        main.add(left, weight=4)
        main.add(right, weight=2)

        self.office = OfficeCanvas(left, root=self.root_path, on_agent_click=self._select_agent)
        self.office.pack(fill="both", expand=True)

        ttk.Label(right, text="TAREFAS").pack(anchor="w", pady=(0, 4))
        self.task_list = tk.Listbox(right, height=8, exportselection=False)
        self.task_list.pack(fill="x")
        self.task_list.bind("<<ListboxSelect>>", self._task_selected)

        ttk.Label(right, text="PAINEL DA TAREFA").pack(anchor="w", pady=(12, 4))
        self.task_panel = tk.Text(right, height=15, wrap="word", state="disabled")
        self.task_panel.pack(fill="both", expand=True)

        ttk.Label(right, text="PAINEL DO FUNCIONÁRIO").pack(anchor="w", pady=(12, 4))
        self.employee_panel = tk.Text(right, height=12, wrap="word", state="disabled")
        self.employee_panel.pack(fill="x")

        chat_row = ttk.Frame(right)
        chat_row.pack(fill="x", pady=(8, 0))
        self.chat_entry = ttk.Entry(chat_row)
        self.chat_entry.pack(side="left", fill="x", expand=True)
        self.chat_entry.bind("<Return>", lambda _e: self._send_chat())
        ttk.Button(chat_row, text="Perguntar", command=self._send_chat).pack(side="left", padx=(6, 0))
        self.chat_answer = ttk.Label(right, text="", wraplength=340, justify="left")
        self.chat_answer.pack(fill="x", pady=(6, 0))

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.config(state="disabled")

    def _new_task(self) -> None:
        NewTaskDialog(self, self._submit_task)

    def _submit_task(self, payload: dict) -> None:
        try:
            case = create_case(payload["process"], payload["represented_as"], root=self.root_path)
            docs = attach_documents(case, payload["files"])
            task_id, _ = create_task(
                case,
                payload["task"],
                payload["represented_as"],
                docs,
                auto_orchestrator=payload["auto_orchestrator"],
                selected_agents=payload["selected_agents"],
            )
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))
            return

        self._refresh_tasks(select_task_id=task_id)

        def worker() -> None:
            try:
                self.engine.run_task(case, task_id)
            except Exception:
                # The workflow persists the exact error in task.json/activity.jsonl.
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_tasks(self, select_task_id: str | None = None) -> None:
        tasks = list_tasks(root=self.root_path)
        current_id = select_task_id or (self.selected_task or {}).get("task_id")
        self.tasks = tasks
        self.task_list.delete(0, "end")
        selected_index = None
        for i, task in enumerate(tasks):
            self.task_list.insert("end", f"{task['task_id']} · {task.get('process','')} · {task.get('status','')}")
            if task.get("task_id") == current_id:
                selected_index = i
        if tasks:
            index = 0 if selected_index is None else selected_index
            self.task_list.selection_set(index)
            self.task_list.activate(index)
            self.selected_task = tasks[index]
            self._refresh_panels()

    def _task_selected(self, _event=None) -> None:
        selection = self.task_list.curselection()
        if not selection:
            return
        self.selected_task = self.tasks[selection[0]]
        self._refresh_panels()

    def _select_agent(self, agent: str) -> None:
        self.selected_agent = agent
        self._refresh_panels()

    def _refresh_panels(self) -> None:
        if not self.selected_task:
            return
        task_path = Path(self.selected_task["_task_path"])
        try:
            task = load_task(task_path)
        except Exception:
            return
        task["_task_path"] = str(task_path)
        task["_case_path"] = self.selected_task["_case_path"]
        self.selected_task = task
        plan_path = task_path / "plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else None
        events = read_events(task["task_id"], root=self.root_path)
        activities = {}
        for agent in ("estagiario", "junior", "senior"):
            agent_events = [e for e in events if e.get("agent") == agent]
            activities[agent] = agent_events[-1].get("description", "") if agent_events else ""
        self.office.update_agents(task.get("agent_states", {}), activities)
        self._set_text(self.task_panel, format_task_panel(task, plan))
        self._set_text(self.employee_panel, format_employee_panel(self.selected_agent, task, events))

    def _poll(self) -> None:
        self._refresh_tasks()
        try:
            while True:
                kind, payload = self.chat_queue.get_nowait()
                if kind == "ok":
                    self.chat_answer.config(text=payload)
                else:
                    self.chat_answer.config(text=f"Erro: {payload}")
        except queue.Empty:
            pass
        self.after(700, self._poll)

    def _send_chat(self) -> None:
        if not self.selected_task:
            return
        question = self.chat_entry.get().strip()
        if not question:
            return
        self.chat_entry.delete(0, "end")
        self.chat_answer.config(text=f"{AGENT_NAMES[self.selected_agent]} está consultando o contexto real da tarefa...")
        case_path = Path(self.selected_task["_case_path"])
        task_id = self.selected_task["task_id"]
        agent = self.selected_agent

        def worker() -> None:
            try:
                result = self.engine.chat_with_agent(case_path, task_id, agent, question)
                self.chat_queue.put(("ok", result.get("answer", "")))
            except Exception as exc:
                self.chat_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _open_folder(self) -> None:
        if not self.selected_task:
            return
        path = Path(self.selected_task["_task_path"])
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Abrir pasta", str(exc))


def main() -> None:
    app = PixelLegalOfficeApp()
    app.mainloop()
