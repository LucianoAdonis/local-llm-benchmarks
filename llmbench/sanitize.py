"""Redact local details from result JSON and from text before it is shown or shared.

llmbench builds its results from known fields and never records paths, host names, user
names or keys in the first place. This pass is the second line of defence: it runs over
every saved result, over what the tool prints (server error messages can quote anything),
and over files produced by the v1 scripts or pasted from engine logs.

No redactor can know every private detail. Read the output before you publish it.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import socket
from pathlib import Path
from typing import Any, List, Optional, Sequence

# --- secrets -----------------------------------------------------------------------
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{16,}|hf_[A-Za-z0-9]{20,}|"
    r"xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|nvapi-[A-Za-z0-9_-]{20,}|"
    r"gsk_[A-Za-z0-9]{20,}|xai-[A-Za-z0-9_-]{20,}|pplx-[A-Za-z0-9_-]{20,}|r8_[A-Za-z0-9]{20,}|tskey-[A-Za-z0-9_-]{16,}|"
    r"[rs]k_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r")(?![A-Za-z0-9_-])"
)
# "sk-" also starts ordinary hyphenated words. A key has a digit in it; a word does not.
_SK_RE = re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_.:-]{17,}")
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=:-]{12,}")
_AUTH_HEADER_RE = re.compile(r"(?i)(authorization\s*[:=]\s*(?:basic|token|bearer)\s+)[^\s\"',;]+")
_KEY_ASSIGN_RE = re.compile(r"(?i)((?:x-)?api[_-]?key\s*[:=]\s*|--api[_-]?key(?:=|\s+))[^\s\"',;&]+")
_URL_CREDENTIALS_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@\"'<>]+:[^/\s@\"'<>]+@")
_QUERY_SECRET_RE = re.compile(r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|key|secret|password)=)[^&\s\"']+")
_ENV_USER_RE = re.compile(r"(?i)\b(USER(?:NAME)?|LOGNAME)=[^\s;\"']+")
# Key names whose string value is a secret, wherever the word sits in the name. "token" is
# matched only as a whole last word, so counters such as prompt_tokens stay.
SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|apikey|secret|passw(?:or)?d|passwd|authorization|cookie|credential|licen[cs]e[_-]?key|(?:^|[_-])token$)")
DROP_KEY_RE = re.compile(r"(?i)(host[_-]?name|user[_-]?name|^user$|computer[_-]?name|serial|uuid|mac[_-]?address|udid)")
# Keys that hold prose someone or some server wrote. Only there is a bare user or host
# name replaced; everywhere else the tool's own words (scenario ids, model and hardware
# names) must survive whatever this machine happens to be called.
FREE_TEXT_KEY_RE = re.compile(r"(?i)(error|message|detail|reason|skipped|label|note|caution|problem|warning|log|line|excerpt|stderr|stdout|output|command|cmd|args)")

# --- paths -------------------------------------------------------------------------
_W = r"[^\\/\"'\s:;,()<>|*?]"                  # one character of a folder name
_WORD = _W + r"+(?:'" + _W + r"+)*"            # O'Brien
# A profile folder may hold spaces ("Alice Smith"), but only when the path goes on after
# it. Otherwise the name is one word, so prose after a bare path is left alone.
_NAME = r"(?:" + _WORD + r"(?: " + _WORD + r"){1,3}(?=[\\/])|" + _WORD + r")"
_START = r"(?:(?<![A-Za-z0-9_])[A-Za-z]:|(?<![A-Za-z0-9_.])|(?<=\s-[A-Za-z]))"
_HOME_RE = re.compile(
    r"(?i)" + _START + r"(?P<prefix>(?:[\\/]+[^\\/\s\"'<>|:;,()]+)*?)[\\/]+(?:Users|home)[\\/]+(?P<name>" + _NAME + r")"
)
_WSL_PREFIX_RE = re.compile(r"(?i)[\\/]+mnt[\\/]+[a-z]")
_MEDIA_RE = re.compile(r"(?i)(?<![A-Za-z0-9_.])((?:/run)?/media/)" + _NAME)
_SHARED_FOLDERS = {"shared", "public", "default", "default user", "all users"}
# A UNC host: two backslashes (four when the text is JSON-escaped), then the server name.
_UNC_RE = re.compile(r"(?<![^\s\"'=(,;])((?:\\{4}|\\{2})(?:\?\\{1,2}UNC\\{1,2})?)(?![\\<])[^\\/\s\"']+")
_SLASH_UNC_RE = re.compile(r"(?<![\w:/.<])//(?!<)[A-Za-z0-9][A-Za-z0-9._-]*(?=/[^/\s])")

# --- network -----------------------------------------------------------------------
_URL_RE = re.compile(r"(?i)\b(?P<scheme>[a-z][a-z0-9+.-]{1,15})://(?P<host>\[[0-9a-f:.%]+\]|[^/\s:@\"'<>\[\]\\]+)(?P<port>:\d{1,5})?")
_PRIVATE_IP = r"(?:192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|169\.254\.\d{1,3}\.\d{1,3})"
_AMBIGUOUS_IP = r"(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})"
_PRIVATE_IP_RE = re.compile(r"^(?:" + _PRIVATE_IP + r"|" + _AMBIGUOUS_IP + r")$")
_LOOPBACK_RE = re.compile(r"(?i)^(?:127(?:\.\d{1,3}){3}|localhost|\[::1\]|0\.0\.0\.0)$")
_LAN_SUFFIX = r"(?:local|lan|localdomain|home\.arpa|home|internal|intranet|corp|ts\.net)"
_LAN_HOST_RE = re.compile(r"(?i)^(?:[^.]+|.*\." + _LAN_SUFFIX + r"|\[f[cde][0-9a-f:%.]*\])$")
_PUBLIC_HOSTS = ("huggingface.co", "hf.co", "github.com", "githubusercontent.com", "gitlab.com", "ollama.com", "lmstudio.ai", "modelscope.cn", "pypi.org", "python.org")
_WEB_SCHEMES = {"http", "https", "ws", "wss"}
_BARE_IP_RE = re.compile(r"(?<![\w.])(?:(?P<sure>" + _PRIVATE_IP + r")|(?P<maybe>" + _AMBIGUOUS_IP + r"))(?![\w]|\.\d)(?P<port>:\d{1,5})?")
_ADDRESS_WORDS = {
    "ip", "host", "address", "addr", "at", "on", "from", "to", "upstream", "server", "endpoint", "connect", "connecting", "connected", "dial",
    "tcp", "udp", "listen", "listening", "bind", "peer", "remote", "gateway", "via", "see", "and", "or", "of", "for", "with", "is", "was", "reach",
}
_IPV6_LOCAL_RE = re.compile(r"(?i)(?<![\w:.])f(?:[cd][0-9a-f]{2}|e[89ab][0-9a-f]):[0-9a-f:]{2,}(?![\w:])")
_LOCAL_HOST_RE = re.compile(r"(?i)(?<![\w.@/-])[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9_-]+)*\." + _LAN_SUFFIX + r"(?![\w-]|\.[a-z0-9])")
_SCP_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._-]+@[A-Za-z0-9][A-Za-z0-9._-]*(?=:[/~])")
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.(?!(?:gguf|bin|safetensors|json|py|txt|log|md|ya?ml|toml)\b)[A-Za-z]{2,}(?![\w-])")
_MAC_RE = re.compile(r"(?<![0-9A-Fa-f:-])(?:(?:[0-9A-Fa-f]{2}:){5}|(?:[0-9A-Fa-f]{2}-){5})[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])")
_GPU_UUID_RE = re.compile(r"\bGPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")

# Words a login or host name may share with ordinary text. Such a name is still removed
# from paths; it is just not hunted as a free-standing word.
_COMMON_NAMES = {
    "user", "users", "admin", "administrator", "root", "test", "guest", "home", "local", "localhost", "runner", "ubuntu", "macbook", "desktop",
    "server", "chat", "long", "model", "models", "context", "control", "sanity", "soak", "parallel", "repeat", "followup", "quick", "standard",
    "deep", "client", "engine", "error", "flags", "usage", "mixed", "diverse", "file", "probe", "default", "argument", "runtime", "loopback",
    "remote", "lmstudio", "ollama", "strata", "llama", "openai", "nvidia", "apple", "intel", "geforce", "radeon", "windows", "linux", "macos",
    "darwin", "python", "will", "with", "from", "this", "that", "arch", "gemma", "qwen", "token", "tokens", "read", "write", "first", "none",
    "true", "false", "null", "main", "data", "work", "dev", "code", "build", "system", "public", "shared", "docker", "debian", "fedora",
}
_MAX_ROUNDS = 4
_SECRETS: List[str] = []


def register_secret(value: Optional[str]) -> None:
    """Remember a literal the user gave us (an API key) so it is removed wherever it turns up."""
    if value and len(value) >= 6 and value not in _SECRETS:
        _SECRETS.append(value)


class Identity:
    """What is known about one machine and account: home folder, login name, host names."""

    def __init__(self, home: Optional[str] = None, user: Optional[str] = None, hosts: Sequence[str] = ()) -> None:
        self.home_patterns: List["re.Pattern[str]"] = []
        if home and home not in ("/", "~") and len(home) > 3:
            variants = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}
            for variant in sorted(variants, key=len, reverse=True):
                self.home_patterns.append(re.compile(re.escape(variant), re.IGNORECASE if os.name == "nt" else 0))
        self.segment_patterns: List["re.Pattern[str]"] = []
        self.word_patterns: List["tuple[re.Pattern[str], str]"] = []
        if user and len(user) >= 2:
            # As a whole path segment the login name is never a coincidence, however short.
            self.segment_patterns.append(re.compile(r"(?<=[\\/])" + re.escape(user) + r"(?=[\\/]|$|[\s\"':;,)])", re.IGNORECASE))
        for name, placeholder in [(user, "<USER>")] + [(host, "<HOST>") for host in hosts]:
            if not name or name.lower() in _COMMON_NAMES:
                continue
            if len(name) >= 4 or (len(name) >= 2 and not name.isascii()):
                self.word_patterns.append((re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.IGNORECASE), placeholder))

    def __bool__(self) -> bool:
        return bool(self.home_patterns or self.segment_patterns or self.word_patterns)

    @classmethod
    def local(cls) -> "Identity":
        """This machine and this account."""
        try:
            user = getpass.getuser()
        except Exception:  # no login name available (some CI and container setups)
            user = ""
        try:
            host = socket.gethostname()
        except OSError:
            host = ""
        return cls(home=os.path.expanduser("~"), user=user, hosts=[h for h in (host, host.split(".")[0]) if h])


def identity_terms() -> Identity:
    """This machine's own home folder, user name and host name."""
    return Identity.local()


def _as_identity(identity: Any) -> Identity:
    if isinstance(identity, Identity):
        return identity
    return Identity.local() if identity is None else Identity()  # an empty list means "none"


def _home(match: "re.Match[str]") -> str:
    if match.group("name").lower() in _SHARED_FOLDERS:
        return match.group(0)
    prefix = match.group("prefix")
    return ("" if _WSL_PREFIX_RE.fullmatch(prefix) else prefix) + "<USER_HOME>"


def _url(match: "re.Match[str]") -> str:
    scheme, host = match.group("scheme").lower(), match.group("host").lower()
    if host.startswith("<") or not host.strip("."):
        return match.group(0)
    if scheme not in _WEB_SCHEMES:
        return "%s://<HOST>" % match.group("scheme")  # sftp, smb, nfs and the like: keep what follows
    if _LOOPBACK_RE.match(host):
        return "<LOCAL_API_URL>"
    if _PRIVATE_IP_RE.match(host) or _LAN_HOST_RE.match(host):
        return "<LAN_API_URL>"
    if any(host == site or host.endswith("." + site) for site in _PUBLIC_HOSTS):
        return match.group(0)
    return "<REMOTE_URL>"


def _bare_ip(match: "re.Match[str]") -> str:
    if match.group("sure") or match.group("port"):
        return "<LAN_IP>"
    # 10.x.x.x is also what a four-part version number looks like ("TensorRT 10.3.5.147").
    # After a product name it is left alone; after an address word or punctuation it goes.
    before = re.search(r"([A-Za-z][\w.+-]*)[ \t]$", match.string[: match.start()])
    if before and before.group(1).lower() not in _ADDRESS_WORDS:
        return match.group(0)
    return "<LAN_IP>"


def _sk(match: "re.Match[str]") -> str:
    return "<REDACTED_SECRET>" if any(char.isdigit() for char in match.group(0)) else match.group(0)


def _once(value: str, identity: Identity, free_text: bool) -> str:
    for secret in _SECRETS:
        value = value.replace(secret, "<REDACTED_SECRET>")
    for pattern in identity.home_patterns:
        value = pattern.sub(lambda _match: "<USER_HOME>", value)
    value = _URL_CREDENTIALS_RE.sub(r"\1<REDACTED>@", value)
    value = _QUERY_SECRET_RE.sub(r"\1<REDACTED>", value)
    value = _URL_RE.sub(_url, value)
    value = _UNC_RE.sub(lambda match: match.group(1) + "<HOST>", value)
    value = _SLASH_UNC_RE.sub("//<HOST>", value)
    value = _HOME_RE.sub(_home, value)
    value = _MEDIA_RE.sub(lambda match: match.group(1) + "<USER>", value)
    for pattern in identity.segment_patterns:
        value = pattern.sub(lambda _match: "<USER>", value)
    value = _ENV_USER_RE.sub(r"\1=<USER>", value)
    value = _AUTH_HEADER_RE.sub(r"\1<REDACTED_SECRET>", value)
    value = _BEARER_RE.sub(r"\1 <REDACTED_SECRET>", value)
    value = _KEY_ASSIGN_RE.sub(r"\1<REDACTED>", value)
    value = _TOKEN_RE.sub("<REDACTED_SECRET>", value)
    value = _SK_RE.sub(_sk, value)
    value = _SCP_RE.sub("<USER>@<HOST>", value)
    value = _EMAIL_RE.sub("<EMAIL>", value)
    value = _MAC_RE.sub("<MAC>", value)
    value = _GPU_UUID_RE.sub("<GPU_UUID>", value)
    value = _BARE_IP_RE.sub(_bare_ip, value)
    value = _IPV6_LOCAL_RE.sub("<LAN_IP>", value)
    value = _LOCAL_HOST_RE.sub("<HOST>", value)
    if free_text:
        for pattern, placeholder in identity.word_patterns:
            value = pattern.sub(lambda _match, text=placeholder: text, value)
    return value


def clean_text(value: str, identity: Any = None, free_text: bool = True) -> str:
    """Redact one string. ``free_text`` also removes a bare login or host name.

    The rules are applied until nothing changes, so the result is stable: cleaning it a
    second time changes nothing.
    """
    who = _as_identity(identity)
    for _ in range(_MAX_ROUNDS):
        cleaned = _once(value, who, free_text)
        if cleaned == value:
            break
        value = cleaned
    return value


def clean(value: Any, identity: Any = None, _free_text: bool = False) -> Any:
    """Return a redacted copy. Keys are cleaned as well as values.

    Bare login and host names are replaced only under keys that hold prose (errors,
    labels, notes, log lines). Paths, addresses and keys are redacted everywhere.
    """
    who = _as_identity(identity)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            name = str(key)
            if DROP_KEY_RE.search(name):
                continue
            safe_key = clean_text(name, Identity(), free_text=False) if isinstance(key, str) else key
            if SECRET_KEY_RE.search(name) and isinstance(item, str) and item:
                result[safe_key] = "<REDACTED>"
            elif SECRET_KEY_RE.search(name) and isinstance(item, (dict, list)) and item:
                result[safe_key] = "<REDACTED>"
            else:
                result[safe_key] = clean(item, who, _free_text or bool(FREE_TEXT_KEY_RE.search(name)))
        return result
    if isinstance(value, list):
        return [clean(item, who, _free_text) for item in value]
    if isinstance(value, str):
        return clean_text(value, who, free_text=_free_text)
    return value


def residue(value: Any) -> bool:
    """True when cleaning would still change something: the file is not safe to publish as is."""
    return clean(value) != value


def read_json(source: Path) -> Any:
    """Read a JSON file in UTF-8 or UTF-16 (what Windows PowerShell 5.1 writes with ``>``)."""
    raw = Path(source).read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    return json.loads(raw.decode(encoding))


def write_json(destination: Path, data: Any) -> None:
    """Write a JSON file whole or not at all, whatever characters the data holds."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    scratch = destination.with_name(destination.name + ".tmp")
    # A lone surrogate (half an emoji from a server that cut a string) cannot be UTF-8;
    # written as an escape it is still valid JSON.
    scratch.write_bytes(text.encode("utf-8", errors="backslashreplace"))
    os.replace(scratch, destination)


def sanitize_file(source: Path, destination: Path) -> None:
    write_json(destination, clean(read_json(source)))
