"""Read tasks assigned to me from a Notion Tasks board you can only read as a guest, via Notion's own API inside the logged-in tab."""
import datetime as dt

from cdp import notion_api
from common import cfg

# Board IDs live in config.toml [notion]; find them in devtools (Network tab, queryCollection request body).
N = cfg().get("notion", {})
COLLECTION, VIEW, SPACE = N.get("collection"), N.get("view"), N.get("space")
P_STATUS = "notion://tasks/status_property"
P_DUE = "notion://tasks/due_date_property"
P_PROJECT = "notion://tasks/task_to_project_relation"
P_ASSIGNEE = "notion://tasks/assign_property"
P_COMPLETED = "`d;l"
P_ID = "cMKv"


def _val(rec):
    v = rec["value"]
    return v.get("value", v)


def _text(prop):
    return "".join(seg[0] for seg in prop or [] if seg and seg[0] != "‣").strip()


def _date(prop):
    for seg in prop or []:
        for fmt in (seg[1] if len(seg) > 1 else []):
            if fmt[0] == "d":
                return fmt[1].get("start_date")
    return None


def _relations(prop):
    return [fmt[1] for seg in prop or [] for fmt in (seg[1] if len(seg) > 1 else []) if fmt[0] == "p"]


def scrape():
    r = notion_api("queryCollection", {
        "collection": {"id": COLLECTION, "spaceId": SPACE},
        "collectionView": {"id": VIEW, "spaceId": SPACE},
        "loader": {"type": "reducer", "reducers": {"collection_group_results": {"type": "results", "limit": 1000}},
                   "filter": {"operator": "and", "filters": [{"property": P_ASSIGNEE, "filter": {
                       "operator": "person_contains", "value": {"type": "relative", "value": "me"}}}]},
                   "sort": [{"property": "Q=<^", "direction": "descending"}],
                   "searchQuery": "", "userTimeZone": N.get("timezone", "UTC")},
    })
    ids = r["result"]["reducerResults"]["collection_group_results"]["blockIds"]
    blocks = r["recordMap"]["block"]

    project_ids = {pid for i in ids for pid in _relations(_val(blocks[i]).get("properties", {}).get(P_PROJECT))}
    names = {}
    if project_ids:
        pr = notion_api("syncRecordValues", {"requests": [
            {"pointer": {"table": "block", "id": pid, "spaceId": SPACE}, "version": -1} for pid in project_ids]})
        for pid, rec in pr["recordMap"].get("block", {}).items():
            names[pid] = _text(_val(rec).get("properties", {}).get("title"))

    rows = []
    for i in ids:
        b = _val(blocks[i])
        p = b.get("properties", {})
        status = _text(p.get(P_STATUS))
        completed = _date(p.get(P_COMPLETED))
        edited = dt.datetime.fromtimestamp(b.get("last_edited_time", 0) / 1000).astimezone().isoformat()
        rows.append({
            "id": i,
            "num": _text(p.get(P_ID)),
            "title": _text(p.get("title")) or "(untitled)",
            "status": status,
            "due": _date(p.get(P_DUE)),
            "project": ", ".join(names.get(x, "") for x in _relations(p.get(P_PROJECT))),
            "url": f"https://app.notion.com/p/{i.replace('-', '')}",
            "finished_on": completed,
            "edited": edited,
        })
    return rows


if __name__ == "__main__":
    import collections
    rows = scrape()
    print(len(rows), collections.Counter(r["project"] for r in rows).most_common(8))
    today = dt.date.today().isoformat()
    for r in rows:
        if r["status"] not in ("Done", "Archived"):
            print(f"{r['status']:12} due {r['due'] or '-':10} {'OVERDUE ' if r['due'] and r['due'] < today else ''}{r['project'][:20]:20} {r['title'][:70]}")
