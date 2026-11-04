"""User settings: ~/.config/a2qlinux/config.toml.

Which value wins, highest first:
    1. a command-line option        (--interface, --close-with-game, --no-auto-update, --exe)
    2. an environment variable      (QUESTLOG_DIR)
    3. this file
    4. the default in SETTINGS

Only behaviour a user may want to change is here. Values that follow from
how Questlog or Wine work (how long Questlog needs to save, wait limits) are
named constants in the code, documented in docs/ARCHITECTURE.md.

Nothing wrong in the file is ignored silently: load() returns each problem
(file, line, what is wrong) next to the settings, using the default for that
setting; the launcher shows them in its window and as a notification.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tomllib

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "a2qlinux" / "config.toml"
# Closing Questlog after the game does not wait for it to save, so the delay
# must cover the time Questlog takes to save game data (see launcher.SAVE_WAIT).
MIN_AFTER_GAME_DELAY = 10.5


@dataclass(frozen=True)
class Setting:
    default: object
    kind: type
    help: str
    choices: tuple = ()
    minimum: float = None


SETTINGS = {
    "questlog_dir": Setting("~/Games/Questlog", str,
                            "Folder with Questlog.exe (the QUESTLOG_DIR environment variable overrides it)."),
    "interface": Setting("", str,
                         "Network interface carrying the game's traffic; empty: the only one besides lo."),
    "after_game": Setting("keep", str,
                          '"keep": Questlog stays open after the game, and Steam sees the game as closed; '
                          '"close": Questlog closes with the game.',
                          choices=("keep", "close")),
    "after_game_delay": Setting(15, (int, float),
                                'With after_game = "close": seconds after the game exits before Questlog closes '
                                f"(a game restarted sooner keeps it open). At least {MIN_AFTER_GAME_DELAY:g}.",
                                minimum=MIN_AFTER_GAME_DELAY),
    "auto_update": Setting(True, bool, "Download new Questlog versions in the background and install them "
                                       "at the next start."),
    "update_check_hours": Setting(6, (int, float), "Hours between checks for a new Questlog.", minimum=0.25),
}


@dataclass(frozen=True)
class Settings:
    questlog_dir: Path
    interface: str
    after_game: str
    after_game_delay: float
    auto_update: bool
    update_check_hours: float


def _line_of(text, key):
    for number, line in enumerate(text.splitlines(), 1):
        if re.match(rf"\s*{re.escape(key)}\s*=", line):
            return number
    return None


def load(path=CONFIG_PATH):
    """(Settings, problems). A missing file is no problem: all defaults."""
    values = {name: spec.default for name, spec in SETTINGS.items()}
    problems = []
    path = Path(path)
    try:
        text = path.read_text()
        data = tomllib.loads(text)
    except FileNotFoundError:
        text, data = "", {}
    except (OSError, UnicodeDecodeError) as error:
        text, data = "", {}
        problems.append(f"{path}: cannot be read ({error}); using the defaults.")
    except tomllib.TOMLDecodeError as error:
        text, data = "", {}
        problems.append(f"{path}: not valid TOML ({error}); using the defaults.")
    for name, value in data.items():
        where = f"{path}, line {_line_of(text, name) or '?'}"
        spec = SETTINGS.get(name)
        if spec is None:
            problems.append(f"{where}: unknown setting '{name}' (known: {', '.join(SETTINGS)}); ignored.")
            continue
        wrong_type = not isinstance(value, spec.kind) or (spec.kind is not bool and isinstance(value, bool))
        if wrong_type:
            problems.append(f"{where}: '{name}' must be {_kind_name(spec.kind)}, not {value!r}; "
                            f"using {spec.default!r}.")
            continue
        if spec.choices and value not in spec.choices:
            problems.append(f"{where}: '{name}' must be one of {', '.join(map(repr, spec.choices))}, "
                            f"not {value!r}; using {spec.default!r}.")
            continue
        if spec.minimum is not None and value < spec.minimum:
            problems.append(f"{where}: '{name}' must be at least {spec.minimum:g}, not {value!r}; "
                            f"using {spec.default!r}.")
            continue
        values[name] = value
    env_dir = os.environ.get("QUESTLOG_DIR")
    values["questlog_dir"] = Path(env_dir or values["questlog_dir"]).expanduser()
    values["after_game_delay"] = float(values["after_game_delay"])
    values["update_check_hours"] = float(values["update_check_hours"])
    return Settings(**values), problems


def _kind_name(kind):
    if kind is bool:
        return "true or false"
    if kind is str:
        return "a quoted text"
    return "a number"


def questlog_dir():
    """Where Questlog is, for the parts that need only that (the menu entry, the Steam wrapper)."""
    return load()[0].questlog_dir


def template(questlog_dir=None):
    """The file a2qlinux-setup writes when there is none: every setting, at its default, explained."""
    lines = ["# A2Qlinux settings. Delete a line to get its default back.",
             "# A command-line option or the QUESTLOG_DIR variable overrides the value here.", ""]
    for name, spec in SETTINGS.items():
        value = str(questlog_dir) if name == "questlog_dir" and questlog_dir else spec.default
        lines.append(f"# {spec.help}")
        lines.append(f"{name} = {_toml(value)}")
        lines.append("")
    return "\n".join(lines)


def set_questlog_dir(questlog_dir, path=CONFIG_PATH):
    """Write `questlog_dir` into the settings file, for a2qlinux-setup --questlog-dir.

    A missing file is created from template(); in an existing one only the
    questlog_dir line changes (or is added), so the user's other settings and
    comments stay as they are.
    """
    path = Path(path)
    line = f"questlog_dir = {_toml(str(questlog_dir))}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template(questlog_dir))
        return
    text = path.read_text()
    new, count = re.subn(r"(?m)^[ \t]*questlog_dir[ \t]*=.*$", lambda _: line, text, count=1)
    if not count:
        new = text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    path.write_text(new)


def _toml(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return repr(value)
