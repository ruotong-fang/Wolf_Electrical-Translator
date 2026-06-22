from pathlib import Path
import sys
import traceback


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ee_translator.app import main


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_path = Path.home() / "EETranslator-error.log"
        details = traceback.format_exc()
        try:
            log_path.write_text(details, encoding="utf-8")
        except OSError:
            pass
        try:
            from tkinter import messagebox
            messagebox.showerror(
                "EETranslator 启动失败",
                f"程序启动时发生错误。\n\n错误日志：{log_path}\n\n{details[-900:]}",
            )
        except Exception:
            pass
        raise
