"""
Process / file relationship graph.

The process tree answers "who launched whom". This module adds the other half
of the question: "which process created this file, and what happened next".

Data is built from detections that Hayabusa already indexed:

* Sysmon EID 1 / Security 4688 -> process creation, parent/child links
* Sysmon EID 11 / 15           -> file creation (TargetFilename)

Only events that matched a rule exist in SQLite, so the graph is a view of the
*flagged* activity, not a full endpoint timeline. The UI says so explicitly.

The output is deliberately small and JSON-friendly. Layout is done in the
browser (no graph library), so this module only returns nodes and edges.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

PROCESS_EIDS = {"1", "4688"}
FILE_EIDS = {"11", "15"}
NETWORK_EIDS = {"3", "22", "5156"}
AUDIT_EIDS = {"5136", "4662", "4719", "4738", "4702", "1102", "4742"}
SYSMON_CHANNEL = "Microsoft-Windows-Sysmon/Operational"

MAX_NODES = 180
MAX_EDGES = 500
MAX_ROWS = 12000

LEVEL_RANK = {"informational": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return ""


def _coerce_details(value: Any) -> dict[str, Any]:
    """Hayabusa's Details field is either a dict or a ¦-separated string."""
    if isinstance(value, dict):
        return dict(value)
    out: dict[str, Any] = {}
    if not isinstance(value, str) or not value:
        return out
    if "¦" not in value:
        return out
    for part in value.split("¦"):
        if ":" not in part:
            continue
        k, _, v = part.partition(":")
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    return out


def _merge_event_fields(event: dict[str, Any]) -> dict[str, Any]:
    """Merge the common shapes Hayabusa emits; ExtraFieldInfo wins."""
    out: dict[str, Any] = {}
    sources = (
        _coerce_details(event.get("Details")),
        event.get("EventData") or {},
        event.get("AllFieldInfo") or {},
        event.get("ExtraFieldInfo") or {},
    )
    for src in sources:
        if not isinstance(src, dict):
            continue
        for key, value in src.items():
            if value not in (None, ""):
                out[str(key)] = value
    return out


def _pid(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        try:
            return str(int(value))
        except (ValueError, OverflowError):
            return str(value)
    return str(value).strip()


def _clean_path(value: Any) -> str:
    s = str(value or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    return s


def _basename(value: Any) -> str:
    s = _clean_path(value)
    if not s:
        return ""
    # Image/CommandLine may be followed by arguments. Prefer the executable
    # portion before the first space for display.
    if s[0] not in "\"'":
        s = s.split(" ", 1)[0]
    s = s.replace("\\", "/").rstrip("/")
    return s.rsplit("/", 1)[-1] or s


def _norm_path(value: Any) -> str:
    return _clean_path(value).replace("\\", "/").rstrip("/").lower()


def _process_key(guid: str, pid: str, image: str) -> str:
    if guid:
        return "p:g:" + guid.lower()
    if pid:
        return "p:i:" + pid + ":" + _basename(image).lower()
    if image:
        return "p:n:" + _norm_path(image)
    return "p:unknown"


def _file_key(path: str) -> str:
    return "f:" + _norm_path(path)


def _ts_min(a: str, b: str) -> str:
    if not a:
        return b or ""
    if not b:
        return a
    return a if a <= b else b


def _ts_max(a: str, b: str) -> str:
    if not a:
        return b or ""
    if not b:
        return a
    return a if a >= b else b


def _detection(row: Any) -> dict[str, Any] | None:
    if not row["rule_id"]:
        return None
    return {
        "job_id": row["job_id"],
        "line_no": row["line_no"],
        "level": row["level"],
        "rule_title": row["rule_title"],
        "rule_id": row["rule_id"],
    }


def _better_detection(old: dict[str, Any] | None,
                      new: dict[str, Any] | None) -> dict[str, Any] | None:
    if not new:
        return old
    if not old:
        return new
    old_rank = LEVEL_RANK.get((old.get("level") or "").lower(), -1)
    new_rank = LEVEL_RANK.get((new.get("level") or "").lower(), -1)
    return new if new_rank > old_rank else old


class _Builder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.present: Counter[str] = Counter()
        self.process_events = 0
        self.file_events = 0
        self.network_events = 0
        self.audit_events = 0
        self.truncated = False

    def proc_node(self, key: str, *, guid: str = "", pid: str = "",
                  image: str = "", cmdline: str = "", user: str = "",
                  integrity: str = "", ts: str = "",
                  synthetic: bool = False) -> dict[str, Any]:
        node = self.nodes.get(key)
        if node is None:
            node = {
                "key": key,
                "type": "process",
                "label": _basename(image) or "(不明なプロセス)",
                "image": _clean_path(image),
                "guid": guid,
                "pid": pid,
                "cmdline": _clean_path(cmdline),
                "user": user,
                "integrity": integrity,
                "ts": ts,
                "last_ts": ts,
                "count": 0,
                "synthetic": synthetic,
                "detection": None,
            }
            self.nodes[key] = node
        # Real observations make a placeholder real and add detail.
        if not synthetic:
            node["synthetic"] = False
        if image and not node.get("image"):
            node["image"] = _clean_path(image)
            node["label"] = _basename(image) or node["label"]
        if guid and not node.get("guid"):
            node["guid"] = guid
        if pid and not node.get("pid"):
            node["pid"] = pid
        if cmdline and len(_clean_path(cmdline)) > len(node.get("cmdline") or ""):
            node["cmdline"] = _clean_path(cmdline)
        if user and not node.get("user"):
            node["user"] = user
        if integrity and not node.get("integrity"):
            node["integrity"] = integrity
        node["ts"] = _ts_min(node.get("ts") or "", ts)
        node["last_ts"] = _ts_max(node.get("last_ts") or "", ts)
        return node

    def file_node(self, path: str, *, image: str = "", ts: str = "") -> dict[str, Any]:
        key = _file_key(path)
        node = self.nodes.get(key)
        if node is None:
            node = {
                "key": key,
                "type": "file",
                "label": _basename(path) or path,
                "path": _clean_path(path),
                "creator_image": _clean_path(image),
                "ts": ts,
                "last_ts": ts,
                "count": 0,
                "synthetic": False,
                "detection": None,
            }
            self.nodes[key] = node
        if image and not node.get("creator_image"):
            node["creator_image"] = _clean_path(image)
        node["ts"] = _ts_min(node.get("ts") or "", ts)
        node["last_ts"] = _ts_max(node.get("last_ts") or "", ts)
        return node

    def network_node(self, key: str, *, label: str, host: str = "",
                     ip: str = "", port: str = "", protocol: str = "",
                     image: str = "", ts: str = "") -> dict[str, Any]:
        node = self.nodes.get(key)
        if node is None:
            node = {
                "key": key,
                "type": "network",
                "label": label,
                "host": host,
                "ip": ip,
                "port": port,
                "protocol": protocol,
                "creator_image": _clean_path(image),
                "ts": ts,
                "last_ts": ts,
                "count": 0,
                "synthetic": False,
                "detection": None,
            }
            self.nodes[key] = node
        if image and not node.get("creator_image"):
            node["creator_image"] = _clean_path(image)
        if host and not node.get("host"):
            node["host"] = host
        if ip and not node.get("ip"):
            node["ip"] = ip
        if port and not node.get("port"):
            node["port"] = port
        if protocol and not node.get("protocol"):
            node["protocol"] = protocol
        node["ts"] = _ts_min(node.get("ts") or "", ts)
        node["last_ts"] = _ts_max(node.get("last_ts") or "", ts)
        return node

    def identity_node(self, key: str, *, label: str, domain: str = "",
                      account: str = "", ts: str = "") -> dict[str, Any]:
        node = self.nodes.get(key)
        if node is None:
            node = {
                "key": key,
                "type": "identity",
                "label": label,
                "domain": domain,
                "account": account,
                "ts": ts,
                "last_ts": ts,
                "count": 0,
                "synthetic": False,
                "detection": None,
            }
            self.nodes[key] = node
        if domain and not node.get("domain"):
            node["domain"] = domain
        if account and not node.get("account"):
            node["account"] = account
        node["ts"] = _ts_min(node.get("ts") or "", ts)
        node["last_ts"] = _ts_max(node.get("last_ts") or "", ts)
        return node

    def object_node(self, key: str, *, label: str, path: str = "",
                    object_type: str = "", ts: str = "") -> dict[str, Any]:
        node = self.nodes.get(key)
        if node is None:
            node = {
                "key": key,
                "type": "object",
                "label": label,
                "path": path,
                "object_type": object_type,
                "ts": ts,
                "last_ts": ts,
                "count": 0,
                "synthetic": False,
                "detection": None,
            }
            self.nodes[key] = node
        if path and not node.get("path"):
            node["path"] = path
        if object_type and not node.get("object_type"):
            node["object_type"] = object_type
        node["ts"] = _ts_min(node.get("ts") or "", ts)
        node["last_ts"] = _ts_max(node.get("last_ts") or "", ts)
        return node

    def edge(self, src: str, dst: str, kind: str, label: str,
             ts: str = "", inferred: bool = False) -> None:
        if not src or not dst or src == dst:
            return
        key = f"{src}|{dst}|{kind}"
        edge = self.edges.get(key)
        if edge is None:
            self.edges[key] = {
                "from": src,
                "to": dst,
                "type": kind,
                "label": label,
                "inferred": inferred,
                "count": 1,
                "ts": ts,
                "last_ts": ts,
            }
            return
        edge["count"] += 1
        edge["ts"] = _ts_min(edge.get("ts") or "", ts)
        edge["last_ts"] = _ts_max(edge.get("last_ts") or "", ts)

    def add(self, row: Any) -> None:
        try:
            event = json.loads(row["raw_json"])
        except (TypeError, ValueError):
            return
        if not isinstance(event, dict):
            return
        self.add_event(event, detection=_detection(row),
                       fallback_ts=str(row["ts"] or ""))

    def add_event(self, event: dict[str, Any],
                  detection: dict[str, Any] | None = None,
                  fallback_ts: str = "") -> None:
        """Add one raw event (timeline JSON or `hayabusa search` JSON)."""
        eid = str(event.get("EventID", event.get("Event ID", "")))
        channel = event.get("Channel") or ""
        self.present[f"{channel or '(不明)'}|{eid or '?'}"] += 1
        if (eid not in PROCESS_EIDS and eid not in FILE_EIDS
                and eid not in NETWORK_EIDS and eid not in AUDIT_EIDS):
            return
        combo = _merge_event_fields(event)
        ts = str(event.get("Timestamp") or fallback_ts or "")

        if eid in PROCESS_EIDS:
            self.process_events += 1
            if eid == "1":
                guid = str(_first(combo, "ProcessGuid", "PGUID"))
                pid = _pid(_first(combo, "ProcessId", "PID"))
                image = _first(combo, "Image", "Proc")
                cmdline = _first(combo, "CommandLine", "Cmdline")
                user = _first(combo, "User")
                integrity = _first(combo, "IntegrityLevel")
                parent_guid = str(_first(combo, "ParentProcessGuid",
                                         "ParentPGUID"))
                parent_pid = _pid(_first(combo, "ParentProcessId",
                                         "ParentPID"))
                parent_image = _first(combo, "ParentImage", "ParentProc")
            else:  # Security 4688
                guid = ""
                pid = _pid(_first(combo, "NewProcessId", "PID"))
                image = _first(combo, "NewProcessName", "Image", "Proc")
                cmdline = _first(combo, "CommandLine", "Cmdline")
                user = _first(combo, "SubjectUserName", "TargetUserName",
                              "User")
                integrity = _first(combo, "MandatoryLabel",
                                   "TokenElevationType", "IntegrityLevel")
                parent_guid = ""
                parent_pid = _pid(_first(combo, "ProcessId", "ParentPID"))
                parent_image = _first(combo, "ParentProcessName",
                                      "ParentImage", "ParentProc")

            if not guid and not pid and not image:
                return
            key = _process_key(guid, pid, image)
            node = self.proc_node(
                key, guid=guid, pid=pid, image=image, cmdline=cmdline,
                user=user, integrity=integrity, ts=ts,
            )
            node["count"] += 1
            node["detection"] = _better_detection(node.get("detection"),
                                                  detection)

            if image:
                fkey = _file_key(image)
                if fkey in self.nodes and self.nodes[fkey]["type"] == "file":
                    self.edge(fkey, key, "execute", "実行（推定）",
                              ts, inferred=True)

            if parent_guid or parent_pid or parent_image:
                pkey = _process_key(parent_guid, parent_pid, parent_image)
                if pkey != key:
                    self.proc_node(
                        pkey, guid=parent_guid, pid=parent_pid,
                        image=parent_image, ts=ts, synthetic=True,
                    )
                    self.edge(pkey, key, "spawn", "起動", ts)
            return

        if eid in FILE_EIDS:
            # File creation (Sysmon 11/15). Image/ProcessGuid identify the
            # process that wrote the file.
            target = _first(combo, "TargetFilename", "FileName", "ObjectName")
            if not target:
                return
            self.file_events += 1
            image = _first(combo, "Image", "Proc", "ProcessName")
            guid = str(_first(combo, "ProcessGuid", "PGUID"))
            pid = _pid(_first(combo, "ProcessId", "PID"))
            fnode = self.file_node(target, image=image, ts=ts)
            fnode["count"] += 1
            fnode["detection"] = _better_detection(fnode.get("detection"),
                                                   detection)

            if image or guid or pid:
                pkey = _process_key(guid, pid, image)
                self.proc_node(
                    pkey, guid=guid, pid=pid, image=image, ts=ts,
                    synthetic=not (guid or pid),
                )
                self.edge(pkey, fnode["key"], "create", "作成", ts)
                if image and _norm_path(image) == _norm_path(target):
                    self.edge(fnode["key"], pkey, "execute", "実行（推定）",
                              ts, inferred=True)
                target_norm = _norm_path(target)
                for other in self.nodes.values():
                    if (other["type"] == "process"
                            and _norm_path(other.get("image") or "")
                            == target_norm):
                        self.edge(fnode["key"], other["key"], "execute",
                                  "実行（推定）", ts, inferred=True)
                        break
            if len(self.nodes) >= MAX_NODES:
                self.truncated = True
            return

        if eid in AUDIT_EIDS:
            # Security audit / account-management events. These carry no process
            # image, so model "actor -> target object/account" instead.
            self.audit_events += 1
            domain = _first(combo, "SubjectDomainName", "TargetDomainName")
            account = _first(combo, "SubjectUserName", "TargetUserName")
            if account and "\\" in str(account):
                actor_label = str(account)
            elif domain and account:
                actor_label = f"{domain}\\{account}"
            else:
                actor_label = str(account or "(不明な実行者)")

            if eid == "4719":
                target_label, target_path, object_type = "監査ポリシー", "", "policy"
                action = "監査ポリシー変更"
            elif eid == "1102":
                target_label, target_path, object_type = "監査ログ", "", "log"
                action = "監査ログ消去"
            elif eid == "4738":
                target_label = str(_first(combo, "TargetUserName", "TargetUserSid")
                                   or "(不明なアカウント)")
                target_path, object_type, action = target_label, "account", "アカウント変更"
            elif eid == "4702":
                target_label = str(_first(combo, "TargetUserName", "TargetUserSid")
                                   or "(不明なアカウント)")
                target_path, object_type, action = target_label, "account", "パスワードリセット"
            elif eid == "4742":
                target_label = str(_first(combo, "TargetUserName", "TargetUserSid")
                                   or "(不明なコンピューター)")
                target_path, object_type, action = target_label, "computer", "コンピューター変更"
            elif eid == "5136":
                target_path = str(_first(combo, "ObjectDN", "ObjectName")
                                  or "(不明なオブジェクト)")
                target_label = target_path.split(",", 1)[0]
                if "=" in target_label:
                    target_label = target_label.split("=", 1)[1]
                target_label = target_label[:60] or target_path[:60]
                attr = str(_first(combo, "AttributeLDAPDisplayName"))
                action = "属性変更" + (f" ({attr})" if attr else "")
                object_type = "directory"
            elif eid == "4662":
                target_path = str(_first(combo, "ObjectName", "ObjectType")
                                  or "(不明なオブジェクト)")
                target_label = target_path.split(",", 1)[0]
                if "=" in target_label:
                    target_label = target_label.split("=", 1)[1]
                target_label = target_label[:60]
                action = "オブジェクト操作"
                object_type = "object"
            else:
                return

            okey = "obj:" + (object_type + ":" + target_path).lower()
            onode = self.object_node(
                okey, label=target_label or target_path or "(不明な対象)",
                path=target_path, object_type=object_type, ts=ts,
            )
            onode["count"] += 1
            onode["detection"] = _better_detection(onode.get("detection"), detection)

            akey = "id:" + actor_label.lower()
            anode = self.identity_node(
                akey, label=actor_label, domain=str(domain), account=str(account),
                ts=ts,
            )
            anode["count"] += 1
            if account or domain:
                self.edge(akey, okey, "audit", action, ts)
            return

        # Network connection (Sysmon EID 3) or DNS query (EID 22).
        self.network_events += 1
        image = _first(combo, "Image", "Proc", "ProcessName")
        guid = str(_first(combo, "ProcessGuid", "PGUID"))
        pid = _pid(_first(combo, "ProcessId", "PID"))
        if eid == "22":
            host = _first(combo, "QueryName", "Query", "DestinationHostname")
            ip = ""
            port = ""
            protocol = "DNS"
            edge_kind, edge_label = "resolve", "名前解決"
        elif eid == "5156":
            # Security WFP permitted connection. No ProcessGuid, and the
            # application path is the best process identity we have.
            host = ""
            ip = _first(combo, "DestAddress", "DestinationIp",
                        "DestinationIP")
            port = _pid(_first(combo, "DestPort", "DestinationPort"))
            protocol = _first(combo, "Protocol")
            image = _first(combo, "Application", "Image", "ProcessName")
            guid = ""
            pid = _pid(_first(combo, "ProcessId", "PID", "ProcessID"))
            edge_kind, edge_label = "connect", "接続"
        else:
            host = _first(combo, "DestinationHostname", "DestinationHostName")
            ip = _first(combo, "DestinationIp", "DestinationIP")
            port = _pid(_first(combo, "DestinationPort"))
            protocol = _first(combo, "Protocol")
            edge_kind, edge_label = "connect", "接続"
        host = "" if str(host).strip() in ("-", "N/A", "n/a") else str(host)
        ip = "" if str(ip).strip() in ("-", "N/A", "n/a") else str(ip)
        protocol = str(protocol or "")
        if protocol == "6":
            protocol = "TCP"
        elif protocol == "17":
            protocol = "UDP"
        label_base = host or ip
        if not label_base:
            return
        label = label_base if not port else f"{label_base}:{port}"
        nkey = "net:" + label.lower()
        nnode = self.network_node(
            nkey, label=label, host=host, ip=ip, port=port,
            protocol=protocol, image=image, ts=ts,
        )
        nnode["count"] += 1
        nnode["detection"] = _better_detection(nnode.get("detection"),
                                               detection)
        if image or guid or pid:
            pkey = _process_key(guid, pid, image)
            self.proc_node(
                pkey, guid=guid, pid=pid, image=image, ts=ts,
                synthetic=not (guid or pid),
            )
            self.edge(pkey, nnode["key"], edge_kind, edge_label, ts)

    def result(self, computer: str, job_id: str | None,
               mode: str = "detections") -> dict[str, Any]:
        # Deterministic order: actors first, then file/network/object leaves.
        order = {"process": 0, "identity": 1, "file": 2, "object": 3,
                 "network": 4}
        ordered = sorted(
            self.nodes.values(),
            key=lambda n: (order.get(n["type"], 9),
                           n.get("ts") or "", n.get("label") or ""),
        )
        ordered = ordered[:MAX_NODES]
        id_of: dict[str, str] = {}
        nodes: list[dict[str, Any]] = []
        for i, node in enumerate(ordered):
            nid = f"n{i}"
            id_of[node["key"]] = nid
            out = {k: v for k, v in node.items() if k != "key"}
            out["id"] = nid
            nodes.append(out)

        edges: list[dict[str, Any]] = []
        for edge in self.edges.values():
            src = id_of.get(edge["from"])
            dst = id_of.get(edge["to"])
            if not src or not dst:
                continue
            out = dict(edge)
            out["from"] = src
            out["to"] = dst
            out["id"] = f"e{len(edges)}"
            edges.append(out)
            if len(edges) >= MAX_EDGES:
                self.truncated = True
                break

        present = [
            {"channel": ch, "event_id": eid, "count": n}
            for key, n in self.present.most_common(10)
            for ch, _, eid in [key.partition("|")]
        ]
        notes: list[str] = []
        where = "ログ" if mode == "all" else "検知データ"
        if self.process_events == 0:
            notes.append(
                f"プロセス作成ログ（Sysmon EID 1 / Security 4688）が{where}に"
                "含まれていません。ファイル作成・ネットワーク接続の実行者だけを"
                "表示します。")
        if self.file_events == 0:
            notes.append(
                f"ファイル作成ログ（Sysmon EID 11）が{where}に含まれていません。"
                "プロセスの起動・ネットワーク接続のみ表示します。")
        if self.audit_events:
            notes.append(
                "アカウント / 監査イベントは「実行者 → 対象アカウント・オブジェクト」"
                "として表示しています。")
        if not nodes:
            notes.append(
                "関係を描けるイベントがありません。プロセス作成、ファイル作成、"
                "ネットワーク接続のいずれかを含むログを指定してください。")

        return {
            "computer": computer,
            "job_id": job_id,
            "mode": mode,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "nodes": len(nodes),
                "processes": sum(1 for n in nodes if n["type"] == "process"),
                "identities": sum(1 for n in nodes if n["type"] == "identity"),
                "files": sum(1 for n in nodes if n["type"] == "file"),
                "objects": sum(1 for n in nodes if n["type"] == "object"),
                "network": sum(1 for n in nodes if n["type"] == "network"),
                "edges": len(edges),
                "process_events": self.process_events,
                "file_events": self.file_events,
                "network_events": self.network_events,
                "audit_events": self.audit_events,
                "truncated": self.truncated,
            },
            "has_data": bool(nodes),
            "present": present,
            "notes": notes,
        }


def build_graph(store, computer: str, job_id: str | None = None,
                include_suppressed: bool = False) -> dict[str, Any]:
    """Build the process/file graph for one computer (optionally one job)."""
    if not computer:
        return {"error": "no computer specified", "nodes": [], "edges": []}

    rows = store.query_detections(
        computer=computer, job_id=job_id,
        include_suppressed=include_suppressed,
        limit=MAX_ROWS, order_by="ts_asc",
    )
    builder = _Builder()
    for row in rows:
        builder.add(row)
        if len(builder.nodes) >= MAX_NODES:
            builder.truncated = True
            break
    return builder.result(computer, job_id, mode="detections")


def build_graph_from_events(computer: str, events: list[dict[str, Any]],
                            job_id: str | None = None,
                            mode: str = "all") -> dict[str, Any]:
    """Build the same graph from raw events (e.g. `hayabusa search` output)."""
    if not computer and mode != "all":
        return {"error": "no computer specified", "nodes": [], "edges": []}
    builder = _Builder()
    for event in events:
        if not isinstance(event, dict):
            continue
        builder.add_event(event)
        if len(builder.nodes) >= MAX_NODES:
            builder.truncated = True
            break
    return builder.result(computer, job_id, mode=mode)
