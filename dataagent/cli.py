"""Chapter entrypoint helper.

A stack trace is the wrong way to tell someone Ollama isn't running. Every
chapter's `__main__` goes through `run_chapter()` so setup problems come out as
instructions instead.
"""

from __future__ import annotations

from collections.abc import Callable

from rich.console import Console

console = Console(stderr=True)


def run_chapter(main: Callable[[], None]) -> None:
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted[/dim]")
        raise SystemExit(130) from None
    except FileNotFoundError as exc:
        # Almost always the missing warehouse.
        console.print(f"\n[red]{exc}[/red]")
        raise SystemExit(1) from None
    except RuntimeError as exc:
        # Provider unreachable — the message already says what to do.
        console.print(f"\n[red]{exc}[/red]")
        raise SystemExit(1) from None
