from __future__ import annotations

from dotenv import load_dotenv

from tools.filesystem import ensure_project_layout


def main() -> None:
    load_dotenv()
    ensure_project_layout()
    from ui.app import main as ui_main
    ui_main()


if __name__ == "__main__":
    main()
