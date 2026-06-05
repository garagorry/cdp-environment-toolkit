"""Build upgrade-planning Excel workbooks from discovery JSON output."""

__all__ = ["main"]


def main(argv=None):
    from .cli import main as _main
    return _main(argv)
