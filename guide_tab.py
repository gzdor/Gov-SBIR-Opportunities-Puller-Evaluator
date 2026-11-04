from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import sbir_guide
import theme


class GuideTabMixin:
    """Offline How-SBIR-works tab."""

    def _build_guide_tab(self) -> None:
        guide = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(guide, text="How SBIR works")
        guide.columnconfigure(1, weight=1)
        guide.rowconfigure(1, weight=1)
        ttk.Label(
            guide,
            text="How the SBIR / STTR program works",
            style="Title.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(
            guide,
            text="Jump",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="nw", padx=(0, 8))
        nav = tk.Listbox(
            guide,
            height=16,
            width=28,
            activestyle="dotbox",
            bg=theme.FIELD,
            fg=theme.FG,
            selectbackground=theme.SELECT,
            highlightthickness=0,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        nav.grid(row=1, column=0, sticky="nsw", padx=(0, 8))
        self._guide_nav = nav
        self.guide_text = tk.Text(
            guide,
            wrap="word",
            state="normal",
            bg=theme.FIELD,
            fg=theme.FG,
            insertbackground=theme.FG,
            selectbackground=theme.SELECT,
            highlightthickness=0,
            borderwidth=0,
            padx=10,
            pady=10,
            spacing1=2,
            spacing3=6,
        )
        scroll = ttk.Scrollbar(guide, command=self.guide_text.yview)
        self.guide_text.configure(yscrollcommand=scroll.set)
        self.guide_text.grid(row=1, column=1, sticky="nsew")
        scroll.grid(row=1, column=2, sticky="ns")
        self.guide_text.tag_configure(
            "title", foreground=theme.FG, font=("Segoe UI", 14, "bold")
        )
        self.guide_text.tag_configure("lead", foreground=theme.MUTED)
        self.guide_text.tag_configure(
            "h", foreground=theme.ACCENT, font=("Segoe UI", 11, "bold")
        )
        self.guide_text.tag_configure("body", foreground=theme.FG)
        self.guide_text.tag_configure("mono", font=("Consolas", 9), foreground=theme.FG)
        self._fill_guide_text()
        nav.bind("<<ListboxSelect>>", self._on_guide_nav)
        links = ttk.Frame(guide)
        links.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(links, text="Open in browser:", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        for index, (label, url) in enumerate(sbir_guide.LINKS):
            ttk.Button(
                links,
                text=label,
                command=lambda dest=url: self._open_guide_link(dest),
            ).grid(row=index // 4, column=(index % 4) + 1, sticky="w", padx=4, pady=2)

    @staticmethod
    def _open_guide_link(url: str) -> None:
        if not url.startswith("https://"):
            return
        import webbrowser

        webbrowser.open(url)

    def _fill_guide_text(self) -> None:
        text = self.guide_text
        nav = self._guide_nav
        text.configure(state="normal")
        text.delete("1.0", "end")
        nav.delete(0, "end")
        text.insert("end", "How the SBIR / STTR program works\n", "title")
        text.insert(
            "end",
            "Local notes for a BD or capture analyst. Official rules win if they "
            "disagree with anything here.\n\n",
            "lead",
        )
        for index, (title, body) in enumerate(sbir_guide.SECTIONS):
            mark = sbir_guide.section_mark(index, title)
            text.mark_set(mark, "end")
            text.mark_gravity(mark, "left")
            nav.insert("end", title)
            text.insert("end", f"{title}\n", "h")
            tag = "mono" if title.startswith("FY27") else "body"
            text.insert("end", f"{body}\n\n", tag)
        text.insert("end", "Links (opens in your browser)\n", "h")
        for label, url in sbir_guide.LINKS:
            text.insert("end", f"• {label}\n  {url}\n", "body")
        text.configure(state="disabled")
        self._guide_marks = [
            sbir_guide.section_mark(index, title)
            for index, title in enumerate(sbir_guide.section_titles())
        ]

    def _on_guide_nav(self, _event: tk.Event | None = None) -> None:
        selection = self._guide_nav.curselection()
        if not selection:
            return
        index = int(selection[0])
        marks = getattr(self, "_guide_marks", [])
        if 0 <= index < len(marks):
            self.guide_text.see(marks[index])
