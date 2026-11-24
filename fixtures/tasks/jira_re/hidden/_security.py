"""The original plugin's security contract, read from its class files and descriptor (t10, owner 2026-11-02).

What the platform enforces from static declarations, so that a missing check in the rewrite shows up without
running Jira. Each item is something the spec states (SPEC.md §1.3 conventions and endpoint "Access" lines; the
claims of ``ww-structure``, ``security-filter`` and ``partitioned-cookie-header-filter``):

* **REST endpoints** (``rest:<METHOD>:<path>``, path parameters as ``{}``): the rewrite's endpoint is not more
  open than the original's. No anonymous marker (``AnonymousAllowed``, ``AnonymousSiteAccess``,
  ``UnrestrictedAccess``) the original lacks, no ``XsrfProtectionExcluded`` it lacks, and ``WebSudoRequired``
  kept. Endpoints of the rewrite beyond the original's must not be anonymous (``rest:extra``).
* **webwork actions** (``action:<alias>``): every command whose ``doX`` method has Jira's ``@RequiresXsrfCheck``
  keeps an XSRF check (the annotation, or a direct call into ``com.atlassian.jira.security.xsrf``), a
  ``@WebSudoRequired`` action keeps it, and no ``@UnrestrictedAccess``/``@AnonymousAllowed`` is added.
* **servlet filters** (``filter:<key>``): the same location and weight, and at least the original's URL patterns
  and dispatchers, so the filter still guards every URL it guarded.

Only the rewrite's items of modules in the run's scope are judged (all modules; ``_support.scope_keys``): an endpoint,
action or filter it does not declare yet, or one of a module the run does not build (its skeleton may map it to a
placeholder), is skipped. Coverage is t02-t04's job, so deleting an item is never a security regression, while
dropping its check is. What these
declarations cannot show (the plugin's own administrator and 'use' gate, checks inside method bodies) needs the
plugin running in a real Jira (docs/jira-re-design.md §7.3).
"""
from __future__ import annotations

import functools
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import _classfile as cf
import _contract as ct

ANONYMOUS = ("AnonymousAllowed", "AnonymousSiteAccess", "UnrestrictedAccess")
XSRF_CHECK = "RequiresXsrfCheck"
XSRF_PACKAGE = "com.atlassian.jira.security.xsrf."
WEBSUDO = "WebSudoRequired"
XSRF_EXCLUDED = "XsrfProtectionExcluded"
NONE = "<no-security-items>"


def norm_path(path: str) -> str:
    """``/a/{id}/b/{name: [a-z]+}`` -> ``/a/{}/b/{}``: a template's parameter names are not visible over HTTP."""
    return re.sub(r"\{[^}]*\}", "{}", path)


# ---------------------------------------------------------------- class files

def _ann_names(raw: cf.RawClass, attrs: dict[str, bytes]) -> set[str]:
    return {a.type.rsplit(".", 1)[-1] for a in cf.annotations(raw, attrs)}


def _hierarchy(classes: dict[str, bytes], name: str) -> list[cf.RawClass]:
    """``name`` and its superclasses as far as ``classes`` has them (Jira's own base classes are not there)."""
    out, seen = [], set()
    while name and name in classes and name not in seen:
        seen.add(name)
        raw = cf.parse_class(classes[name])
        out.append(raw)
        name = raw.superclass
    return out


def _invokes_package(raw: cf.RawClass, code: bytes, package: str) -> bool:
    """Whether ``code`` (a Code attribute) has an invoke instruction on a method of a class in ``package``. The
    scan reads every byte as a possible opcode; a stray match would also need its operand to name a method
    reference of that package, which is not a realistic accident."""
    (n,) = struct.unpack_from(">I", code, 4)
    body = code[8:8 + n]
    for i in range(len(body) - 2):
        if body[i] in (0xB6, 0xB7, 0xB8, 0xB9):          # invokevirtual, -special, -static, -interface
            (idx,) = struct.unpack_from(">H", body, i + 1)
            ref = raw.pool.get(idx)
            if ref and ref[0] in (10, 11):                 # Methodref, InterfaceMethodref
                (cls_idx,) = struct.unpack_from(">H", ref[1], 0)
                if raw.class_name(cls_idx).startswith(package):
                    return True
    return False


@dataclass
class Action:
    alias: str
    xsrf: dict[str, bool] = field(default_factory=dict)   # command -> has an XSRF check
    websudo: bool = False
    anonymous: bool = False
    module: str | None = None                             # the webwork1 module's key


def _command(method: str) -> str:
    return method[2].lower() + method[3:] if method != "doExecute" else "default"


def action_security(classes: dict[str, bytes], name: str, alias: str) -> Action:
    """The commands (``doX`` methods, inherited ones included) of the action class ``name`` and their checks. A
    command's check is that of the class that declares the method nearest to ``name``: Jira reads the
    annotation of the method it invokes."""
    act = Action(alias)
    for raw in _hierarchy(classes, name):
        anns = _ann_names(raw, raw.attrs)
        act.websudo |= WEBSUDO in anns
        act.anonymous |= bool(anns & set(ANONYMOUS))
        for m in raw.methods:
            if not (m.name.startswith("do") and len(m.name) > 2 and m.name[2].isupper()) or m.descriptor != "()Ljava/lang/String;":
                continue
            cmd = _command(m.name)
            if cmd in act.xsrf:
                continue
            code = m.attrs.get("Code")
            act.xsrf[cmd] = XSRF_CHECK in _ann_names(raw, m.attrs) or (
                code is not None and _invokes_package(raw, code, XSRF_PACKAGE))
    return act


# ---------------------------------------------------------------- descriptors

def _module_tag(el: ET.Element) -> str:
    return el.tag.split("}", 1)[-1] if isinstance(el.tag, str) else ""


def actions(root: ET.Element, classes: dict[str, bytes], jira: str | None) -> dict[str, Action]:
    out: dict[str, Action] = {}
    for el in root:
        if _module_tag(el) != "webwork1" or (jira and not ct.applies(el, jira)):
            continue
        for a in el.iter("action"):
            alias, name = a.get("alias"), a.get("name")
            if alias and name in classes and alias not in out:
                out[alias] = action_security(classes, name, alias)
                out[alias].module = el.get("key")
    return out


@dataclass
class Filter:
    key: str
    location: str | None
    weight: str | None
    patterns: set[str]
    dispatchers: set[str]


def filters(root: ET.Element, jira: str | None, expand=lambda v: v) -> dict[str, Filter]:
    out: dict[str, Filter] = {}
    for el in root:
        key = expand(el.get("key"))
        if _module_tag(el) != "servlet-filter" or not key or key in out or (jira and not ct.applies(el, jira)):
            continue
        out[key] = Filter(key, el.get("location"), el.get("weight"),
                          {(u.text or "").strip() for u in el.iter("url-pattern")},
                          {(d.text or "").strip() for d in el.iter("dispatcher")} or {"REQUEST"})   # servlet default
    return out


def endpoints(root: ET.Element, classes: dict[str, bytes], jira: str | None,
              modules: dict[str, str] | None = None) -> dict[str, ct.Endpoint]:
    """``{rest:<METHOD>:<path>: endpoint}``; an endpoint declared twice (two ``<restrict>`` variants without a
    version to choose) keeps its first declaration. ``modules`` receives each endpoint's ``<rest>`` module key."""
    out: dict[str, ct.Endpoint] = {}
    mods = ct.rest_modules(root, jira) if jira else [
        (el.get("key"), "/rest/" + "/".join(s.strip("/") for s in (el.get("path", ""), el.get("version", ""))
                                            if s.strip("/")), [p.text.strip() for p in el.findall("package") if p.text])
        for el in root if _module_tag(el) == "rest"]
    for key, base, packages in mods:
        for e in ct.rest_endpoints(classes, packages, base):
            item = f"rest:{e.method}:{norm_path(e.path)}"
            out.setdefault(item, e)
            if modules is not None:
                modules.setdefault(item, key)
    return out


# ---------------------------------------------------------------- the reference (the original)

@dataclass
class Reference:
    endpoints: dict[str, ct.Endpoint]
    actions: dict[str, Action]
    filters: dict[str, Filter]
    rest_modules: dict[str, str] = field(default_factory=dict)   # rest item -> its <rest> module key

    def ids(self) -> list[str]:
        return [*self.endpoints, *(f"action:{a}" for a in self.actions), *(f"filter:{k}" for k in self.filters)]

    def module_of(self, item: str) -> str | None:
        """The plugin module an item belongs to, so a run judges only the modules in its scope."""
        kind, _, name = item.partition(":")
        if kind == "rest":
            return self.rest_modules.get(item)
        return self.actions[name].module if kind == "action" else name


def original(jar: Path, extra_jars: list[Path], jira: str | None) -> Reference:
    """``extra_jars``: the internal libraries the plugin bundles (``../vendor/lib/``), where some of its action
    base classes live (the ``!apply`` command's ``doApply``)."""
    root = ct.descriptor(jar)
    if root is None:
        return Reference({}, {}, {})
    classes = ct.jar_classes(jar)
    for extra in extra_jars:
        for name, data in cf.classes_in_jar(extra).items():
            classes.setdefault(name, data)
    rest_modules: dict[str, str] = {}
    return Reference(endpoints(root, classes, jira, rest_modules), actions(root, classes, jira), filters(root, jira),
                     rest_modules)


# ---------------------------------------------------------------- judging the rewrite

def endpoint_problems(want: ct.Endpoint, got: ct.Endpoint) -> list[str]:
    out = []
    if got.anonymous and not want.anonymous:
        out.append(f"is open to anonymous callers ({', '.join(s for s in got.security if s in ANONYMOUS)}); "
                   "the original requires a logged-in user")
    if XSRF_EXCLUDED in got.security and XSRF_EXCLUDED not in want.security:
        out.append("opts out of the platform's XSRF protection (XsrfProtectionExcluded); the original does not")
    if WEBSUDO in want.security and WEBSUDO not in got.security:
        out.append("does not require websudo (WebSudoRequired); the original does")
    return out


def action_problems(want: Action, got: Action) -> list[str]:
    out = [f"command {cmd!r} has no XSRF check (@RequiresXsrfCheck); the original's has"
           for cmd, checked in sorted(want.xsrf.items()) if checked and got.xsrf.get(cmd) is False]
    if want.websudo and not got.websudo:
        out.append("does not require websudo (@WebSudoRequired); the original does")
    if got.anonymous and not want.anonymous:
        out.append("is marked for unrestricted or anonymous access; the original is not")
    return out


def filter_problems(want: Filter, got: Filter) -> list[str]:
    out = []
    if got.location != want.location:
        out.append(f"location is {got.location!r}; the original's is {want.location!r}")
    if want.weight is not None and got.weight != want.weight:
        out.append(f"weight is {got.weight!r}; the original's is {want.weight!r}")
    if missing := sorted(want.patterns - got.patterns):
        out.append(f"no longer guards URL pattern(s) {missing}")
    if missing := sorted(want.dispatchers - got.dispatchers):
        out.append(f"no longer runs for dispatcher(s) {missing}")
    return out
