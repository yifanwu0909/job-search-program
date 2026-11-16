"""pipeline.py — the while-loop driver (shadow-mode v1).

The loop, per the design:
    while verified_total < window_target and window_open:
        item = next_item()                 # diversification order, split respected
        work_order = build_order(item)     # answers, resume, portal, salary figure
        result = agent_browser_step(...)   # Muse drives the browser (NOT here)
        record(result)                     # fixed-format log entry, counters move
        if submitted: schedule_verification(item)

This module never touches a browser. `next_order()` recomputes state from the
log, checks the stop conditions IN CODE, verifies preconditions IN CODE, and
emits ONE work order as a dict. `record()` consumes a result dict and writes
the outcome through log_writer. A `friction` result sets a stop file that
makes every later `next_order()` refuse until the user / a logged all-clear clears it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

import discovery as discovery_mod
import events as events_mod
import log_writer
import state as state_mod

BASE = Path(__file__).resolve().parent.parent


def _load_yaml(name: str) -> dict:
    with (BASE / "config" / name).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify_divergences(divergences, overall_event_state, prior_trail):
    """Split state-check divergences into BENIGN and DEEP (the user, Nov 5,
    2026: "Don't send divergence message anymore unless there's a deeper
    issue. Burn this in code.").

    BENIGN — the mismatch is fully explained by the records themselves:
      * the event book already holds this exact outcome for the item,
        under another window (a confirmation-email catch-up re-mentioned
        in the open window's prose — Navan #198 / Stripe #203,
        Nov 5, 2026);
      * the item is a carried item with a prose trail from before this
        window and the prose side carries the note (a pre-go-live
        outcome, Socure #187; a carried park re-noted as captcha,
        TRM Labs #182; a carried bench item whose limbo note is
        prose-only, Super.com #267);
      * a presence-only park mismatch (a limbo/staged event present on
        one side only) on such an item, whose folded dispositions agree.
    DEEP — the mismatch is NOT explained:
      * the event book is AHEAD of the prose log (events hold an outcome
        the prose never recorded, or a verified the prose does not) — a
        submission missing from the log is a duplicate risk;
      * a prose outcome for an item with no event trail anywhere and no
        prose trail before this window — a phantom, or an outcome that
        silently bypassed spine.py record on a fresh item.
    `overall_event_state` maps item_id -> the item's folded disposition
    across ALL windows, in prose vocabulary ("verified" for a folded
    "submitted"); `prior_trail` is the set of item ids with a parsed log
    event before the open window's section. Returns (deep, benign);
    each entry is the divergence dict plus "class" and "reason". The
    watcher messages the user only when a COUNTING divergence (the verified
    totals differ) includes at least one DEEP item; benign divergences
    are recorded in the shadow log and the morning report only.
    """
    def _presence_only(d):
        return ("-event present" in d["prose"]
                or "-event absent" in d["prose"]
                or "-event present" in d["events"]
                or "-event absent" in d["events"])

    deep: list[dict] = []
    benign: list[dict] = []
    main_class: dict[int, str] = {}
    for d in divergences:
        if _presence_only(d):
            continue
        iid, p, e = d["item_id"], d["prose"], d["events"]
        if e != "(absent)" and p == "(absent)":
            cls, why = "deep", ("event book holds an outcome the prose "
                                "log never recorded")
        elif e == "verified" and p != "verified":
            cls, why = "deep", ("event book is ahead of the prose log "
                                "on the verified count")
        elif p != "(absent)" and overall_event_state.get(iid) == p:
            cls, why = "benign", ("event book holds this outcome under "
                                  "an earlier window (catch-up re-mention)")
        elif p != "(absent)" and iid in prior_trail:
            cls, why = "benign", ("carried item — the outcome is carried "
                                  "in prose from an earlier window")
        else:
            cls, why = "deep", ("no event trail and no earlier prose "
                                "trail — unexplained")
        main_class[iid] = cls
        (deep if cls == "deep" else benign).append(
            {**d, "class": cls, "reason": why})
    for d in divergences:
        if not _presence_only(d):
            continue
        iid = d["item_id"]
        if main_class.get(iid) == "deep":
            cls, why = "deep", ("presence mismatch on an item with a "
                                "deep divergence")
        elif iid in prior_trail or iid in overall_event_state:
            cls, why = "benign", ("presence-only park mismatch on a "
                                  "known item (folded states agree)")
        else:
            cls, why = "deep", ("presence mismatch on an item with no "
                                "event trail and no earlier prose trail "
                                "— unexplained")
        (deep if cls == "deep" else benign).append(
            {**d, "class": cls, "reason": why})
    deep.sort(key=lambda d: d["item_id"])
    benign.sort(key=lambda d: d["item_id"])
    return deep, benign


class Spine:
    def __init__(self, log_path: str | None = None,
                 events_path: str | None = None):
        self.rules = _load_yaml("rules.yaml")
        self.answers = _load_yaml("answers.yaml")
        paths = self.rules.get("paths", {})
        self.log_path = log_path or str(
            Path(paths["outreach_log"]).expanduser())
        # The functional log lives at program/events.jsonl for the live log.
        # For any other log (test copies), it sits beside that log under a
        # derived name so a test can never write the live event stream.
        if events_path:
            self.events_path = Path(events_path)
        elif log_path:
            lp = Path(log_path)
            self.events_path = lp.parent / f"{lp.stem}.events.jsonl"
        else:
            self.events_path = BASE / "events.jsonl"
        self.resumes_dir = Path(paths["tailored_resumes_dir"]).expanduser()
        self.state_dir = BASE / "state"
        self.state_dir.mkdir(exist_ok=True)
        # The friction flag lives beside the event book for any
        # non-default setup (a test or log copy), exactly like the
        # open-piles file below — a test can never read or write the
        # live flag. (Before Nov 7, 2026 the flag always resolved to
        # the live state dir, so the run_tests friction round-trip
        # read the LIVE flag; isolated since the lane-scope change.)
        if events_path or log_path:
            self.friction_file = self.events_path.parent / "FRICTION.flag"
        else:
            self.friction_file = self.state_dir / "FRICTION.flag"
        self.verify_queue_file = self.state_dir / "verify_queue.json"
        # The open-piles track file (the user, Nov 6, 2026): the live program
        # writes state/open_piles.json; any non-default setup (a test or
        # a log copy) writes beside its own event book instead, so a
        # test can never touch the live track file.
        if events_path or log_path:
            self.piles_file = self.events_path.parent / "open_piles.json"
        else:
            self.piles_file = self.state_dir / "open_piles.json"
        # The stocked-items data file (STOCKING AS DATA, the user, Nov 6,
        # 2026) sits beside the event book; events.stocked_path_for
        # is the one derivation rule stock.py and this reader share.
        self.stocked_path = events_mod.stocked_path_for(self.events_path)
        self._stocked_cache: dict | None = None

    # ------------------------------------------------------------ friction
    def friction_active(self) -> dict | None:
        if self.friction_file.exists():
            try:
                return json.loads(self.friction_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"signal": "friction flag present (unreadable)"}
        return None

    def friction_scope(self, fric: dict | None = None) -> str | None:
        """Which lane(s) an active friction flag stops (the user, Nov 7,
        2026: "when LinkedIn stopped stocking, use jobright").

        Returns None (no flag), "linkedin" (LinkedIn lane only —
        external discovery (Jobright + Indeed + the CareerOps scan)
        and external-sourced orders continue), or
        "all" (full stop). The scope is data the flag carries from
        record() time: the triggering item's source. A flag with no
        recorded scope — every flag set before Nov 7, 2026, whose file
        holds only set_at/signal/item_id — reads as "linkedin" when
        the item's source is LINKEDIN and as "all" when the item is
        unknown (not in the log) or external-sourced: never widen a
        stop on a guess, and never narrow one either."""
        fric = fric if fric is not None else self.friction_active()
        if not fric:
            return None
        scope = fric.get("scope")
        if scope in ("linkedin", "all"):
            return scope
        iid = fric.get("item_id")
        it = self.load_state().items.get(iid) if iid else None
        src = ((it.source if it else "") or "").upper()
        return "linkedin" if src in ("LINKEDIN", "LINKEDIN_ALERT") else "all"

    def set_friction(self, signal: str, item_id: int | None,
                     scope: str | None = None,
                     alert_lane_blocked: bool = False):
        flag = {"set_at": datetime.now(state_mod.CT).isoformat(),
                "signal": signal, "item_id": item_id,
                "scope": scope}
        if alert_lane_blocked:
            # The friction was raised ON an alert-sourced item (a
            # fresh LinkedIn warning/checkpoint during alert work):
            # the alert lane pauses with the LinkedIn lane. A flag
            # raised on a plain LINKEDIN item does NOT block the
            # alert lane (the user, Nov 12, 2026 — alert Easy Apply volume
            # is small: "EZ applies are okay").
            flag["alert_lane_blocked"] = True
        self.friction_file.write_text(json.dumps(flag, indent=2),
                                      encoding="utf-8")

    def alert_lane_blocked(self, fric: dict | None = None,
                           st=None) -> bool:
        """True when the active friction flag also pauses the
        LinkedIn-alert lane: the flag carries the marker, or (a
        scope-less legacy flag) its triggering item is
        LINKEDIN_ALERT-sourced."""
        fric = fric if fric is not None else self.friction_active()
        if not fric:
            return False
        if fric.get("alert_lane_blocked"):
            return True
        iid = fric.get("item_id")
        if iid:
            st = st if st is not None else self.load_state()
            it = st.items.get(iid)
            if it and (it.source or "").upper() == "LINKEDIN_ALERT":
                return True
        return False

    def clear_friction(self, note: str, log_path: str | None = None):
        entry = log_writer.append_entry(
            log_path or self.log_path,
            f"ALL-CLEAR — friction flag cleared: {note} (spine program).")
        events_mod.append_event(self.events_path, "friction_cleared")
        if self.friction_file.exists():
            self.friction_file.unlink()
        return entry

    # ------------------------------------------------------- event stream
    def _win_for(self, st: state_mod.LogState, it) -> str | None:
        """The window an event for this item counts toward: the last batch
        section at or before the item's latest logged activity (a pre-open
        one-off like Turo still lands in the section it was worked under).
        Falls back to the latest section in the log."""
        if not st.windows:
            return None
        if it is not None and it.events:
            last_line = max(e[0] for e in it.events)
            win = None
            for w in st.windows:
                if w.section_line <= last_line:
                    win = w
            if win is not None:
                return win.date
        return st.windows[-1].date

    def _event(self, etype: str, st: state_mod.LogState, it,
               source: str = "", why: str | None = None,
               with_src: bool = True):
        """The functional-log twin of a prose entry: same call, same moment,
        so the two representations cannot drift apart. Minimal shape only
        ({ts, type, item, src, win[, why]}) — the prose entry carries the
        detail. with_src=False for source-less events (friction_set)."""
        src = (source or "").upper()
        events_mod.append_event(
            self.events_path, etype,
            item=(it.id if it is not None else None),
            src=src if (with_src and src in events_mod.SOURCES) else None,
            win=self._win_for(st, it), why=why)

    def state_check(self, wdate: str | None = None) -> dict:
        """Shadow-mode comparison: state parsed from the prose log vs state
        folded from the event stream, for one window. Compares the tally
        sets (verified by source, staged, captcha, limbo); every item whose
        compared disposition differs is a DIVERGENCE."""
        st = self.load_state()
        w = st.window_for(wdate)
        ws = st.window_status(w.date)
        prose_verified = {
            (src or "UNKNOWN").upper(): {it.id for it in items}
            for src, items in ws["verified_by_source"].items()}
        raw_events = events_mod.read_events(self.events_path)
        folded = state_mod.fold_events(raw_events, w)
        companies = {it.id: it.company for it in st.items.values()}
        for iid, rec in folded["items"].items():
            companies.setdefault(iid, rec["company"])

        def prose_disp(iid):
            if any(iid in ids for ids in prose_verified.values()):
                return "verified"
            if iid in {it.id for it in ws["staged"]}:
                return "staged"
            if iid in {it.id for it in ws["captcha"]}:
                return "captcha"
            if iid in {it.id for it in ws["limbo"]}:
                return "limbo"
            return "(absent)"

        def event_disp(iid):
            if iid in folded["verified"]:
                return "verified"
            if iid in folded["staged"]:
                return "staged"
            if iid in folded["captcha"]:
                return "captcha"
            if iid in folded["limbo"]:
                return "limbo"
            return "(absent)"

        universe = (set().union(*prose_verified.values())
                    if prose_verified else set())
        universe |= {it.id for it in ws["staged"]}
        universe |= {it.id for it in ws["captcha"]}
        universe |= {it.id for it in ws["limbo"]}
        universe |= (folded["verified"] | folded["staged"]
                     | folded["captcha"] | folded["limbo"])
        divergences = []
        for iid in sorted(universe):
            p, e = prose_disp(iid), event_disp(iid)
            if p != e:
                divergences.append({"item_id": iid,
                                    "company": companies.get(iid, ""),
                                    "prose": p, "events": e})
        # Fix (c), Nov 4, 2026: ALSO compare RAW EVENT PRESENCE for the
        # two kinds a fold can shadow — limbo and staged — for this
        # window's MEMBER items only (the union of the window's own
        # lists, the same membership the seed fixture and window_status
        # use; an old item re-mentioned in the section is not a member
        # and its stray mentions are not window state). The folded
        # comparison alone certified Fetch #180 as consistent while its
        # limbo was invisible to every pile. If either side has a limbo
        # (or staged) event for a member item in this window and the
        # other side has none, that is a divergence even when the
        # folded dispositions agree.
        member_ids = set()
        for key in ("verified", "staged", "captcha", "limbo", "bench",
                    "claimed"):
            member_ids |= {it.id for it in ws[key]}
        member_ids |= (folded["verified"] | folded["staged"]
                       | folded["captcha"] | folded["limbo"])
        for kind in ("limbo", "staged"):
            prose_has = {it.id for it in st.items.values()
                         if it.id in member_ids
                         and any(e[0] >= w.section_line
                                 for e in it.events_of(kind))}
            events_has = {int(ev["item"]) for ev in raw_events
                          if ev.get("type") == kind
                          and ev.get("item") is not None
                          and int(ev["item"]) in member_ids
                          and state_mod._window_relevant(ev, w)}
            for iid in sorted(prose_has ^ events_has):
                divergences.append({
                    "item_id": iid,
                    "company": companies.get(iid, ""),
                    "prose": (f"{kind}-event present" if iid in prose_has
                              else f"{kind}-event absent"),
                    "events": (f"{kind}-event present" if iid in events_has
                               else f"{kind}-event absent")})
        # Divergence classification (the user, Nov 5, 2026 — see
        # classify_divergences): every divergence is classed benign or
        # deep from the records themselves, so the watcher can stay
        # silent on explained mismatches and message only a deeper issue.
        overall = state_mod.fold_events(raw_events, None)
        overall_state = {}
        for iid, rec in overall["items"].items():
            folded_state = rec.get("state") or ""
            if folded_state:
                overall_state[iid] = ("verified"
                                      if folded_state == "submitted"
                                      else folded_state)
        prior_trail = {it.id for it in st.items.values()
                       if any(e[0] < w.section_line for e in it.events)}
        deep_divs, benign_divs = classify_divergences(
            divergences, overall_state, prior_trail)
        return {
            "window": w.date,
            "prose": {
                "verified_total": ws["verified_total"],
                "verified_by_source": {s: sorted(ids) for s, ids
                                       in prose_verified.items()},
                "staged": sorted(it.id for it in ws["staged"]),
                "captcha": sorted(it.id for it in ws["captcha"]),
                "limbo": sorted(it.id for it in ws["limbo"])},
            "events": {
                "verified_total": len(folded["verified"]),
                "verified_by_source": {s: sorted(ids) for s, ids
                                       in folded["verified_by_source"].items()},
                "staged": sorted(folded["staged"]),
                "captcha": sorted(folded["captcha"]),
                "limbo": sorted(folded["limbo"])},
            "divergences": divergences,
            "deep_divergences": deep_divs,
            "benign_divergences": benign_divs,
            "deep_divergence": bool(deep_divs),
        }

    # ------------------------------------------------------- targets
    def effective_targets(self, st: state_mod.LogState,
                          wdate: str | None = None) -> dict:
        """Window targets with the friction ladder APPLIED IN CODE
        (audit fix, Nov 4, 2026): a window with a friction signal drops
        the NEXT window one step (40→30→26→20, floor 20); a clean window
        at a dropped step climbs back one. Computed from the event book's
        friction_set events across all past windows — never hand-edited,
        so the ladder can no longer sit in config doing nothing."""
        cfg = self.rules["window"]
        ladder = cfg.get("friction_ladder") or [cfg["targets"]["linkedin"]]
        floor = cfg.get("friction_floor", ladder[-1])
        base = dict(cfg["targets"])
        w = st.window_for(wdate)
        events = events_mod.read_events(self.events_path)
        step = 0
        for past in st.windows:
            if past.date >= w.date:
                break
            had = any(ev.get("type") == "friction_set"
                      and state_mod._window_relevant(ev, past)
                      for ev in events)
            if had:
                step = min(step + 1, len(ladder) - 1)
            elif step > 0:
                step -= 1
        linkedin = max(ladder[step], floor)
        flex = bool((cfg.get("source_flex") or {}).get(
            "jobright_covers_linkedin_shortfall"))
        # INDEED (the user, Nov 12, 2026): a third discovery source feeding
        # the SAME window total. Jobright and Indeed each carry the
        # full split figure and the configured total stays binding,
        # so the total is read from config — never summed across
        # sources (summing would multiply-count the shared 60).
        # LINKEDIN ALERTS (the user, Nov 12, 2026): a fourth figure on the
        # same terms — LinkedIn job alerts via the daily alert emails
        # feed the SAME total; the total binds, never a sum.
        # CAREEROPS (the user, Nov 16, 2026): the career-ops scan is a
        # fifth figure on the exact same terms — an ADDITIONAL worker
        # source alongside Jobright and Indeed (her replacement idea
        # was reversed the same day); the total still binds.
        total = base.get("total", linkedin + base["jobright"])
        return {"linkedin": linkedin, "jobright": base["jobright"],
                "indeed": base.get("indeed", 0),
                "careerops": base.get("careerops", 0),
                "linkedin_alert": base.get("linkedin_alert", 0),
                "total": total,
                "ladder_step": step, "configured": base,
                "jobright_flex_cover": flex}

    def _submission_history(self, st: state_mod.LogState) -> list[dict]:
        """Every submitted item's (host, ats, ts) — the raw material for
        the pacing checks (audit fix, Nov 4, 2026: pacing lived only in
        prose; next_order now enforces it)."""
        out = []
        for it in st.items.values():
            sub = it.submitted_event
            if not sub or not sub[1]:
                continue
            route, _sal = self._route_and_salary(st, it)
            url = route.get("url", "")
            out.append({"item_id": it.id,
                        "host": urlparse(url).netloc if url else "",
                        "ats": route.get("ats", ""), "ts": sub[1]})
        return out

    # -------------------------------------------------------------- status
    def load_state(self) -> state_mod.LogState:
        return state_mod.parse_log(self.log_path)

    def status(self, wdate: str | None = None) -> dict:
        st = self.load_state()
        return self._status_of(st, wdate)

    def _status_of(self, st: state_mod.LogState, wdate: str | None) -> dict:
        ws = st.window_status(wdate)
        targets = self.effective_targets(st, wdate)
        by_source = {
            src.upper(): items for src, items in ws["verified_by_source"].items()}
        expected_blocked = self.rules["blocked_companies"]["expected_total"]
        return {
            "window": ws["window"],
            "targets": targets,
            "verified_total": ws["verified_total"],
            "verified_by_source": {
                src: [{"id": it.id, "company": it.company, "role": it.role}
                      for it in items] for src, items in by_source.items()},
            "verified_counts": {src: len(items)
                                for src, items in by_source.items()},
            "staged": [{"id": it.id, "company": it.company, "role": it.role,
                        "step": (it.events_of("staged") or [("", "", "")])[-1][3]}
                       for it in ws["staged"]],
            "captcha": [{"id": it.id, "company": it.company, "role": it.role,
                         "step": (it.events_of("captcha") or [("", "", "")])[-1][3]}
                        for it in ws["captcha"]],
            "manual_packets": [
                {"id": it.id, "company": it.company, "role": it.role,
                 "step": (it.events_of("packet") or [("", "", "")])[-1][3]}
                for it in ws["packet"]],
            "limbo": [{"id": it.id, "company": it.company} for it in ws["limbo"]],
            "bench": [{"id": it.id, "company": it.company, "source": it.source}
                      for it in ws["bench"]],
            "claimed_unfinished": [
                {"id": it.id, "company": it.company} for it in ws["claimed"]],
            "company_slots_used": ws["company_slots_used"],
            "all_time_verified_by_company": ws["all_time_verified_by_company"],
            "blocked_total_in_log": ws["blocked_total_in_log"],
            "blocked_expected": expected_blocked,
            "blocked_check_ok": ws["blocked_total_in_log"] == expected_blocked,
            "friction": self.friction_active(),
            "friction_scope": self.friction_scope(),
            "presentation": (
                (self.rules.get("presentation") or {}).get("rule")
                if (ws["staged"] or ws["captcha"]) else None),
            "log_lines": ws["log_lines"],
            "log_path": self.log_path,
        }

    # ------------------------------------------------- open piles file
    def open_piles(self, st: state_mod.LogState | None = None) -> dict:
        """EVERY still-open captcha and manual-packet item, across ALL
        windows (the user, Nov 6, 2026: "How are you keeping track of all
        these capture? or manual application that I have been found
        the time to do myself?" — the answer is now this, in code).

        Membership is folded from the EVENT BOOK (the governing record
        for state): an item is on a pile when its folded state is
        "captcha" or "packet"; a later submitted / skipped / unstaged
        event takes it off. Company, role, source and the step text
        come from the prose parse — names and detail, never state.
        Each entry carries the ts and window of the event that put it
        on the pile, so how long the user has been waiting on it is data,
        not memory. Sorted oldest first."""
        st = st or self.load_state()
        events = events_mod.read_events(self.events_path)
        folded = state_mod.fold_events(events)
        last_ev: dict[int, dict] = {}
        for ev in events:
            if ev.get("type") in ("captcha", "packet") \
                    and ev.get("item") is not None:
                last_ev[int(ev["item"])] = ev
        captcha, packets = [], []
        for iid, rec in folded["items"].items():
            kind = rec["state"]
            if kind not in ("captcha", "packet"):
                continue
            it = st.items.get(iid)
            ev = last_ev.get(iid) or {}
            prose = (it.events_of(kind) if it is not None else [])
            entry = {
                "item_id": iid,
                "company": it.company if it is not None else "",
                "role": it.role if it is not None else "",
                "source": rec["source"] or (it.source if it is not None else ""),
                "window": ev.get("win"),
                "since": ev.get("ts"),
                "step": prose[-1][3] if prose else "",
            }
            (captcha if kind == "captcha" else packets).append(entry)
        captcha.sort(key=lambda e: e["since"] or "")
        packets.sort(key=lambda e: e["since"] or "")
        return {"captcha": captcha, "manual_packets": packets}

    def _write_piles_file(self, st: state_mod.LogState | None = None) -> dict:
        """Rebuild state/open_piles.json from open_piles() — the track
        file for everything waiting on the user herself (captcha takeovers
        and manual packets), across all windows. Called on EVERY
        recorded outcome (record_with_check) and by `spine.py piles`,
        the same pattern as the forward to-dos track file: the file is
        a pure rebuild from the records, never hand-edited."""
        piles = self.open_piles(st)
        payload = {
            "updated_at": datetime.now(state_mod.CT).isoformat(),
            "captcha_open_count": len(piles["captcha"]),
            "manual_open_count": len(piles["manual_packets"]),
            "captcha": piles["captcha"],
            "manual_packets": piles["manual_packets"],
        }
        self.piles_file.parent.mkdir(parents=True, exist_ok=True)
        self.piles_file.write_text(json.dumps(payload, indent=2),
                                   encoding="utf-8")
        return payload

    # ---------------------------------------------------------- work order
    def _stocked_items(self) -> dict:
        """The stocked-items data file: item id -> the stocking
        payload stock.py wrote as fixed data at stocking time
        (items stocked earlier were backfilled once by
        backfill_stocked.py). Cached per Spine instance; {} when
        the file does not exist."""
        if self._stocked_cache is None:
            data: dict = {}
            if self.stocked_path.exists():
                try:
                    raw = json.loads(
                        self.stocked_path.read_text(encoding="utf-8"))
                    data = {int(k): v for k, v in raw.items()}
                except (ValueError, TypeError):
                    data = {}
            self._stocked_cache = data
        return self._stocked_cache

    def _route_and_salary(self, st: state_mod.LogState, item) -> tuple[dict, dict]:
        """Route + salary from the item's STOCKING DATA — never from
        log prose. The regex miner that used to dig them out of the
        STOCKED segments was deleted Nov 6, 2026 (fix #1 of the
        text-parsing audit): it silently returned empty routes for
        re-stocked items, whose STOCKED line names the original
        item before the apply URL, so segments() cut the segment
        before the URL. An item with no data record resolves empty,
        exactly as an unresolvable route did before."""
        route = {"url": "", "ats": ""}
        salary = {"published_range": None, "figure": None,
                  "rule": self.answers["applications"]["salary_rule"]}
        rec = self._stocked_items().get(item.id)
        if not rec:
            return route, salary
        route["url"] = rec.get("url") or ""
        route["ats"] = rec.get("ats") or ""
        if rec.get("synthesized"):
            route["synthesized"] = True
        pay = rec.get("pay") or {}
        if pay.get("figure") is not None:
            salary["figure"] = pay["figure"]
        if rec.get("salary_range"):
            salary["published_range"] = rec["salary_range"]
            salary["rule"] = "top of published range"
        return route, salary

    @staticmethod
    def _ds_rank(role: str | None) -> int | None:
        """DS-track rank for bench ordering: 0 = Senior Data Scientist,
        1 = plain Data Scientist, None = not a DS-track role."""
        r = (role or "").lower()
        if "data scientist" not in r:
            return None
        head = r.split("data scientist")[0]
        return 0 if re.search(r"\b(senior|sr)\b", head) else 1

    @classmethod
    def _ds_priority_order(cls, bench: list) -> list:
        """SENIOR DS FIRST, THEN PLAIN DS (the user, Nov 3, 2026; confirmed
        Nov 8, 2026 — "Senior DS first, then plain DS"): reorder ONLY
        the DS-track items among the bench slots DS items already
        occupy, Senior before plain (stable inside each tier). The
        caller's diversification order still governs, and non-DS items
        keep their exact positions — the DS priority applies within
        the DS track only."""
        slots = [i for i, it in enumerate(bench)
                 if cls._ds_rank(it.role) is not None]
        if len(slots) < 2:
            return bench
        ds_items = sorted((bench[i] for i in slots),
                          key=lambda it: cls._ds_rank(it.role))
        out = list(bench)
        for i, it in zip(slots, ds_items):
            out[i] = it
        return out

    def next_order(self, wdate: str | None = None,
                   now: datetime | None = None) -> dict:
        fric = self.friction_active()
        fric_scope = self.friction_scope(fric) if fric else None
        if fric and fric_scope == "all":
            return {"status": "stopped", "reason": "friction flag set",
                    "friction": fric}
        jobright_only = fric_scope == "linkedin"
        st = self.load_state()
        ws = st.window_status(wdate)
        targets = self.effective_targets(st, wdate)
        if ws["verified_total"] >= targets["total"]:
            return {"status": "complete", "reason": "window target reached",
                    "verified_total": ws["verified_total"]}
        w = st.window_for(wdate)
        now = now or datetime.now(state_mod.CT)
        if now >= w.close_dt:
            return {"status": "closed", "reason": "window closed",
                    "closes": w.close_dt.isoformat()}
        # No-new-starts cutoff (audit fix, Nov 4, 2026): config has always
        # said 07:45 CT; the code only checked the 08:23 close. Enforce it.
        cutoff_txt = (self.rules["window"].get("no_new_starts_after_ct")
                      or "07:45")
        ch, cm = (int(x) for x in cutoff_txt.split(":"))
        cutoff_dt = w.close_dt.replace(hour=ch, minute=cm, second=0,
                                       microsecond=0)
        if now >= cutoff_dt:
            return {"status": "closed",
                    "reason": f"no new starts after {cutoff_txt} CT "
                              f"(pre-close cutoff)",
                    "closes": w.close_dt.isoformat()}
        counts = {src.upper(): len(v)
                  for src, v in ws["verified_by_source"].items()}
        alert_blocked = self.alert_lane_blocked(fric, st) \
            if jobright_only else False
        if jobright_only:
            # JOBRIGHT FALLBACK (the user, Nov 7, 2026): LinkedIn friction
            # stops the LinkedIn lane only. The count target becomes
            # the whole remaining window need — Jobright flex cover
            # for the entire LinkedIn share, total still binding.
            # Since Nov 12, 2026 the fallback covers BOTH external
            # sources: Indeed carries on the exact Jobright rules, so
            # its target becomes the total too. Since Nov 16, 2026 it
            # covers the CareerOps scan as well — a third external
            # worker source on the same terms, so its target becomes
            # the total too. LinkedIn alerts ride
            # the same fallback (their lane is not the stopped one),
            # so the alert target becomes the total as well.
            targets = {**targets,
                       "linkedin": counts.get("LINKEDIN", 0),
                       "jobright": targets["total"],
                       "indeed": targets["total"],
                       "careerops": targets["total"],
                       "linkedin_alert": targets["total"]}
        slots = set(ws["company_slots_used"])
        # Diversification ORDER in code (audit fix, Nov 4, 2026): companies
        # with no prior all-time verified application first; a company with
        # 4+ all-time verified is fill-in only (served last); FIFO by
        # stocking order inside each group. (The 1-per-window cap was
        # already enforced via company_slot_free below.)
        div_cfg = self.rules.get("diversification") or {}
        fill_in_at = div_cfg.get("fill_in_all_time_verified_threshold", 4)
        all_time = ws["all_time_verified_by_company"]

        def _bench_key(it):
            prior = all_time.get(state_mod.normalize_company(it.company), 0)
            return (1 if prior >= fill_in_at else 0,
                    1 if prior > 0 else 0,
                    min(e[0] for e in it.events if e[2] == "stocked"))

        bench = sorted(ws["bench"], key=_bench_key)
        # DS PRIORITY IN CODE (the user, Nov 8, 2026): Senior DS served
        # before plain DS, within the DS track only (see
        # _ds_priority_order) — diversification groups above still
        # govern, non-DS items keep their positions.
        bench = self._ds_priority_order(bench)
        # Pacing, enforced in code (audit fix, Nov 4, 2026): portal lane —
        # same host ≥30 min apart, ≤10 per host per window; LinkedIn lane —
        # Easy Apply ≥45 min apart, ≤2 per hour. Lane separation: the
        # same-host rules never apply to Easy Apply items and vice versa.
        pacing_cfg = self.rules.get("pacing") or {}
        portal_cfg = pacing_cfg.get("portal_lane") or {}
        ea_cfg = pacing_cfg.get("easy_apply") or {}
        hist = self._submission_history(st)
        skipped = []
        pacing_held = []
        for it in bench:
            route, salary = self._route_and_salary(st, it)
            host = urlparse(route.get("url", "")).netloc if route.get("url") else ""
            is_ea = route.get("ats") == "LinkedIn Easy Apply"
            checks = []
            # GATE BACKLOG (the user, Nov 12, 2026): gate timing is
            # on_identification again and stock.py refuses NEW
            # deferred stocks, so any item whose gate reads
            # "deferred" was stocked/submitted under the Nov 11,
            # 2026 deferral — pre-reversal backlog. It stays
            # servable untouched; if it moves forward still
            # verdict-less, the gate runs then via the gate packet
            # before anything proceeds.
            gate_deferred_ok = it.gate == "deferred"
            checks.append({"check": "gate_pass_recorded",
                           "ok": it.gate in ("pass", "alert")
                                 or gate_deferred_ok,
                           "detail": f"gate={it.gate or 'not recorded'}"})
            src = it.source or "UNKNOWN"
            if jobright_only:
                if src == "LINKEDIN_ALERT" and not alert_blocked:
                    # THE ALERT LANE (the user, Nov 12, 2026): alert-sourced
                    # items are their own lane. The LinkedIn friction
                    # flag does NOT stop them and does not need
                    # clearing for them — Easy Apply via the daily
                    # alert email is allowed ("EZ applies are okay.
                    # There aren't that many of them anyway."). The
                    # LinkedIn DISCOVERY ban is untouched: the alert
                    # email link is the only entry, no searches.
                    checks.append({
                        "check": "linkedin_lane_stopped",
                        "ok": True,
                        "detail": "alert lane — LINKEDIN_ALERT is its "
                                  "own lane: servable despite the "
                                  "LinkedIn friction flag; Easy Apply "
                                  "via the alert email is allowed "
                                  "(the user, Nov 12, 2026)"})
                elif src == "LINKEDIN_ALERT":
                    checks.append({
                        "check": "linkedin_lane_stopped",
                        "ok": False,
                        "detail": "alert lane paused — the active "
                                  "friction was raised on an "
                                  "alert-sourced item (a fresh LinkedIn "
                                  "warning/checkpoint during alert "
                                  "work stops the alert lane too, "
                                  "the user, Nov 12, 2026)"})
                else:
                    checks.append({
                        "check": "linkedin_lane_stopped",
                        "ok": src in ("JOBRIGHT", "INDEED", "CAREEROPS"),
                        "detail": "LinkedIn friction — LinkedIn lane "
                                  "stopped; external sources only — "
                                  "Jobright + Indeed + the CareerOps "
                                  "scan (the user, Nov 7, 2026; "
                                  "Indeed added Nov 12, 2026; CareerOps "
                                  "scan added Nov 16, 2026); the "
                                  "LinkedIn-alert lane runs separately"})
            tgt = targets.get(src.lower())
            src_open = tgt is not None and counts.get(src, 0) < tgt
            flex_note = ""
            if (not src_open and src in ("JOBRIGHT", "INDEED", "CAREEROPS", "LINKEDIN_ALERT")
                    and targets.get("jobright_flex_cover")
                    and counts.get("LINKEDIN", 0) < (targets.get("linkedin")
                                                     or 0)
                    and ws["verified_total"] < (targets.get("total") or 0)):
                # SOURCE FLEX (the user, Nov 4, 2026): Jobright covers a
                # LinkedIn shortfall past its 20 split; total binding.
                # Indeed rides the same flex on the same terms (the user,
                # Nov 12, 2026 — "exact same rule" as Jobright), and the
                # CareerOps scan rides it too (added Nov 16, 2026).
                src_open = True
                flex_note = " (flex cover: LinkedIn short)"
            checks.append({"check": "source_target_open",
                           "ok": src_open,
                           "detail": f"{src} {counts.get(src, 0)}/{tgt}"
                                     f"{flex_note}"})
            checks.append({"check": "company_slot_free",
                           "ok": state_mod.normalize_company(it.company) not in slots,
                           "detail": it.company})
            resume_path = (self.resumes_dir / it.resume_file) if it.resume_file else None
            checks.append({"check": "tailored_resume_on_disk",
                           "ok": bool(resume_path and resume_path.exists()),
                           "detail": it.resume_file or "no resume recorded"})
            checks.append({"check": "not_already_submitted",
                           "ok": it.submitted_event is None,
                           "detail": it.state})
            next_at = None
            if is_ea:
                ea_hist = sorted(
                    (h for h in hist if h["ats"] == "LinkedIn Easy Apply"),
                    key=lambda h: h["ts"])
                min_gap = ea_cfg.get("min_gap_minutes", 45)
                max_hr = ea_cfg.get("max_per_hour", 2)
                ok, detail = True, "no prior Easy Apply submission"
                if ea_hist:
                    last = ea_hist[-1]["ts"]
                    gap = (now - last).total_seconds() / 60
                    in_hour = sum(1 for h in ea_hist
                                  if (now - h["ts"]).total_seconds() < 3600)
                    if gap < min_gap:
                        ok = False
                        next_at = last + state_mod.timedelta(minutes=min_gap)
                        detail = f"last Easy Apply {gap:.0f} min ago (< {min_gap})"
                    elif in_hour >= max_hr:
                        ok = False
                        oldest = min(h["ts"] for h in ea_hist
                                     if (now - h["ts"]).total_seconds() < 3600)
                        next_at = oldest + state_mod.timedelta(minutes=60)
                        detail = f"{in_hour} Easy Apply submissions in the last hour (max {max_hr})"
                    else:
                        detail = f"last Easy Apply {gap:.0f} min ago; {in_hour} in the last hour"
                checks.append({"check": "easy_apply_pacing", "ok": ok,
                               "detail": detail})
            elif host:
                same = [h for h in hist if h["host"] == host]
                gap_min = portal_cfg.get("same_host_min_gap_minutes", 30)
                ok, detail = True, f"no prior {host} submission"
                if same:
                    last = max(h["ts"] for h in same)
                    gap = (now - last).total_seconds() / 60
                    if gap < gap_min:
                        ok = False
                        next_at = last + state_mod.timedelta(minutes=gap_min)
                        detail = f"last {host} submission {gap:.0f} min ago (< {gap_min})"
                    else:
                        detail = f"last {host} submission {gap:.0f} min ago"
                checks.append({"check": "same_host_gap", "ok": ok,
                               "detail": detail})
                cap = portal_cfg.get("same_host_max_per_window", 10)
                in_win = sum(1 for h in same
                             if w.open_dt <= h["ts"] < w.close_dt)
                checks.append({"check": "same_host_window_cap",
                               "ok": in_win < cap,
                               "detail": f"{in_win}/{cap} {host} submissions this window"})
            failed = [c for c in checks if not c["ok"]]
            if failed:
                skipped.append({"item_id": it.id, "company": it.company,
                                "failed": [c["check"] for c in failed]})
                if next_at is not None and all(
                        c["check"] in ("same_host_gap", "easy_apply_pacing")
                        for c in failed):
                    pacing_held.append({"item_id": it.id, "company": it.company,
                                        "next_at": next_at.isoformat()})
                continue
            route_limit = (self.rules.get("route_limits") or {}).get(host)
            return {
                "status": "work_order",
                "work_order": {
                    "item_id": it.id, "company": it.company, "role": it.role,
                    "source": src, "linkedin_job_id": it.linkedin_job_id,
                    "route": route, "salary": salary,
                    "route_limit": route_limit,
                    "wu_step_expected": route_limit["wu_step"] if route_limit else None,
                    "packet_handoff": bool(route_limit and route_limit.get("packet_handoff")),
                    "humanizer_required": bool((self.rules.get("writing") or {}).get("humanizer_required")),
                    "humanizer_applies_to": (self.rules.get("writing") or {}).get("applies_to"),
                    "humanizer_attestation_marker": (self.rules.get("writing") or {}).get("attestation_marker"),
                    "sign_in": self.rules.get("sign_in"),
                    "fill_policy": self.rules.get("fill_policy"),
                    "staging": self.rules.get("staging"),
                    "captcha_ip_block": self.rules.get("captcha_ip_block"),
                    "stocking": self.rules.get("stocking"),
                    "pay_filter": self.rules.get("pay_filter"),
                    "role_filter": self.rules.get("role_filter"),
                    "discovery": self.rules.get("discovery"),
                    "discovery_plan": discovery_mod.build_plan(self.rules,
                    answers=self.answers),
                    "hold_protocol": self.rules.get("hold_protocol"),
                    "pacing": pacing_cfg,
                    "resume_path": str(resume_path),
                    "answers": {"applicant": self.answers["applicant"],
                                "applications": self.answers["applications"]},
                    "preconditions": checks,
                    "blockers_that_may_stage": self.rules["true_blockers"],
                    "window_counts": {"verified_total": ws["verified_total"],
                                      "by_source": counts,
                                      "targets": targets},
                    "jobright_only_mode": jobright_only,
                    "lane_restriction": (
                        "LINKEDIN LANE STOPPED (friction) — external "
                        "sources (Jobright + Indeed + the CareerOps "
                        "scan) plus the "
                        "LinkedIn-alert lane carry the window: "
                        "no LinkedIn discovery or search, no LinkedIn "
                        "SSO (use Google SSO), no LinkedIn People gate "
                        "checks; stock and fly Jobright-, Indeed-, "
                        "CareerOps- and "
                        "LinkedIn-alert-sourced items; Easy Apply is "
                        "allowed ONLY for alert-sourced items reached "
                        "via the daily alert email (the user, Nov 12, 2026: "
                        "\"EZ applies are okay\")"
                        + (" — EXCEPT the alert lane is ALSO paused: "
                           "the active friction was raised on an "
                           "alert-sourced item"
                           if alert_blocked else "")
                        if jobright_only else None),
                },
            }
        if pacing_held:
            return {"status": "pacing_hold",
                    "reason": "every ready item is inside a pacing gap; "
                              "the earliest clears at next_at",
                    "next_at": min(h["next_at"] for h in pacing_held),
                    "held": pacing_held, "skipped": skipped,
                    "stocking": self.rules.get("stocking"),
                    "pay_filter": self.rules.get("pay_filter"),
                    "role_filter": self.rules.get("role_filter"),
                    "discovery": self.rules.get("discovery"),
                    "discovery_plan": discovery_mod.build_plan(self.rules,
                    answers=self.answers),
                    "claimed_unfinished": [it.id for it in ws["claimed"]],
                    "jobright_only_mode": jobright_only,
                    "discovery_sources": (
                        ["JOBRIGHT", "INDEED", "CAREEROPS", "LINKEDIN_ALERT"] if jobright_only
                        else ["LINKEDIN", "JOBRIGHT", "INDEED", "CAREEROPS", "LINKEDIN_ALERT"])}
        return {"status": "empty", "reason": "no bench item passes preconditions",
                "skipped": skipped,
                "stocking": self.rules.get("stocking"),
                "pay_filter": self.rules.get("pay_filter"),
                "role_filter": self.rules.get("role_filter"),
                "discovery": self.rules.get("discovery"),
                "discovery_plan": discovery_mod.build_plan(self.rules,
                    answers=self.answers),
                "claimed_unfinished": [it.id for it in ws["claimed"]],
                "jobright_only_mode": jobright_only,
                "discovery_sources": (
                    ["JOBRIGHT", "INDEED", "CAREEROPS", "LINKEDIN_ALERT"] if jobright_only
                    else ["LINKEDIN", "JOBRIGHT", "INDEED", "CAREEROPS", "LINKEDIN_ALERT"])}

    # --------------------------------------------------------------- record
    def _enqueue_verify(self, item_id: int, company: str):
        queue = []
        if self.verify_queue_file.exists():
            queue = json.loads(self.verify_queue_file.read_text(encoding="utf-8"))
        queue.append({"item_id": item_id, "company": company,
                      "submitted_at": datetime.now(state_mod.CT).isoformat(),
                      "checks": []})
        self.verify_queue_file.write_text(json.dumps(queue, indent=2),
                                          encoding="utf-8")

    def record(self, result: dict, log_path: str | None = None) -> str:
        log_path = log_path or self.log_path
        st = state_mod.parse_log(log_path)
        iid = int(result["item_id"])
        it = st.items.get(iid)
        view = {"id": iid,
                "company": (it.company if it else result.get("company", "")),
                "role": (it.role if it else result.get("role", ""))}
        source = (it.source if it else result.get("source", "")) or ""
        outcome = result["outcome"]
        # DUPLICATE GUARD (the user, Nov 7, 2026 — the #471 replay: the tool
        # layer re-delivered ONE record call ~26 times; the FIRST
        # delivery wrote its prose line but the event twin never
        # landed, and every later delivery appended BOTH sides,
        # because nothing asked "is this outcome already recorded
        # for this item?" before writing. Counts never moved — state
        # folds by rank, so copies are idempotent there — but the log
        # and the event book filled with duplicates). A record is a
        # DUPLICATE — refused before anything is written, like every
        # guard below — only when BOTH hold:
        #   (1) the item has NO outcome event yet in this event book
        #       (every completed record() call lands one; a book full
        #       of friction_set signals does NOT count as an outcome —
        #       but then the book's newest write is still OLDER than
        #       a prose-only outcome, see (2)), and
        #   (2) the prose log proves this outcome for the item at a
        #       moment NOT EARLIER than the book's latest write for
        #       the item — i.e. the outcome landed in prose while its
        #       event twin never arrived: the signature of the one
        #       half-completed write being replayed.
        # The prose proof uses the state check's own eyes
        # (state.prose_event_kinds: the binding classify_divergence
        # uses), so guard and state check can never disagree on what
        # is already recorded — an earlier draft checked only the
        # prose HEAD and refused a limbo->staged workflow the state
        # check itself calls consistent. DATA only: types and
        # timestamps; no prose text is read. The replay's own later
        # copies each carry an event twin, so (1) fails for them and
        # they land — the guard stops the DUPLICATED FACT from being
        # re-asserted as new, and the state check's benign catch-up
        # remains the arbiter of the copies that exist. Deliberate
        # exceptions: `friction` (repeated friction signals are each
        # real) and the prose-only outcomes (post_submit_pending /
        # exception carry no event type — _RECORD_EVENT_TYPE maps
        # them to None — so they cannot be checked this way).
        _dup_type = self._RECORD_EVENT_TYPE.get(outcome)
        if _dup_type is not None and outcome != "friction":
            _item_events = [e for e in events_mod.read_events(
                self.events_path)
                if int(e.get("item") or -1) == iid]
            _has_outcome = any(
                e.get("type") in self._OUTCOME_EVENT_TYPES
                for e in _item_events)
            _last_book_ts = None
            for _e in _item_events:
                _t = events_mod._parse_ts(_e.get("ts"))
                if _t is not None and (
                        _last_book_ts is None or _t > _last_book_ts):
                    _last_book_ts = _t
            _prose_ts = (state_mod.prose_outcome_ts(log_path)
                         .get(iid) or {}).get(_dup_type)
            _prose_hit = _prose_ts is not None and (
                _last_book_ts is None or _prose_ts >= _last_book_ts)
            if not _has_outcome and _prose_hit:
                raise ValueError(
                    f"REFUSED — item #{iid}: outcome '{outcome}' "
                    f"was already recorded for this item in prose "
                    f"with no event-book twin — this record is a "
                    f"replay of a half-completed write "
                    f"(rules.yaml counting.idempotent_records). "
                    f"Nothing was written. The state check treats "
                    f"the prose outcome as the item's on-file fact; "
                    f"do not record the same outcome twice.")
        # Every recorded outcome writes BOTH representations in this call:
        # the human-readable prose entry (rich — it carries the detail) and
        # the minimal structured event ({ts, type, item, src, win[, why]}).
        if outcome == "submitted":
            entry = log_writer.append_entry(log_path, log_writer.submitted(
                view, result.get("portal", ""), result.get("confirmation", ""),
                source, result.get("submitted_by", "")))
            self._event("submitted", st, it, source)
            self._enqueue_verify(iid, view["company"])
            return entry
        if outcome == "email_verified":
            entry = log_writer.append_entry(log_path, log_writer.email_verified(
                view, result.get("message_id", ""), result.get("sender", ""),
                result.get("subject", "")))
            self._event("verified", st, it, source)
            return entry
        if outcome == "staged":
            # CLASSIFY IN DATA, NEVER IN PROSE (the user, Nov 5, 2026, late:
            # "No you are parsing the text with hardcoded keywords
            # again. Use LLM for this type of questions. Only give
            # code what it can easily digest: dictionary or other
            # data structure.") The division of labor: the RUN — the
            # LLM, which saw the screen — classifies the blocker into
            # the closed vocabulary rules.yaml staging.blocker_kinds
            # and sends it as DATA (blocker_kind). The code below
            # checks only that data and the item's route (host / ATS —
            # also data). The step/blocker prose is the human record;
            # NO guard reads it. An unclassified park is refused: the
            # code cannot check what it cannot digest.
            if not (result.get("step") or "").strip() \
                    and not (result.get("blocker") or "").strip():
                raise ValueError(
                    f"REFUSED — item #{iid}: a staged record must "
                    f"name its step and blocker; an unexplained park "
                    f"is never written. Nothing was written.")
            _kinds = (self.rules.get("staging") or {}).get(
                "blocker_kinds") or []
            _kind = result.get("blocker_kind")
            if _kind not in _kinds:
                raise ValueError(
                    f"REFUSED — item #{iid}: a staged record must "
                    f"carry blocker_kind, one of {_kinds} (rules.yaml "
                    f"staging.blocker_kinds) — the run classifies "
                    f"what it saw; the code checks data, never prose. "
                    f"Nothing was written.")
            _host = ""
            _ats = ""
            if it is not None:
                try:
                    _route0, _sal0 = self._route_and_salary(st, it)
                    _host = urlparse(_route0.get("url") or "").netloc
                    _ats = _route0.get("ats") or ""
                except Exception:
                    _host, _ats = "", ""
            _is_wd = _host.endswith("myworkdayjobs.com") \
                or _ats == "Workday"
            _is_sf = "successfactors" in _host or _ats == "SuccessFactors"
            _is_gem = _host == "jobs.gem.com" or _ats == "Gem"
            _si = self.rules.get("sign_in") or {}
            # GUARD (the user, Nov 5, 2026 — Sony #388): a Workday sign-in
            # NEVER stages — accounts are per-tenant, so the run
            # follows sign_in.workday_failure_path (SSO, then CREATE
            # the account with the saved password, verify by email
            # in-flow, finish). Data in, decision out.
            if _si.get("workday_failure_never_stage") and _is_wd \
                    and _kind == "sign_in":
                raise ValueError(
                    f"REFUSED — item #{iid}: a Workday sign-in never "
                    f"stages for the user (rules.yaml "
                    f"sign_in.workday_failure_path: SSO, then CREATE "
                    f"the tenant account with the saved Workday "
                    f"password — Workday accounts are per-tenant, so "
                    f"sign-in alone cannot work until it exists — "
                    f"verify by email in-flow, finish the "
                    f"application). Nothing was written.")
            # GUARD (the user, Nov 6, 2026 — #427 Ericsson, #433 Ascend
            # Learning, live tap session: "You need to create an
            # account. Not just login... do like Workday"):
            # SuccessFactors accounts are per-tenant too — a sign-in
            # failure NEVER stages; the run follows
            # sign_in.successfactors_failure_path (SSO, then CREATE
            # the tenant account with the saved SuccessFactors
            # password — one password, not a cross-tenant account —
            # verify by email in-flow, finish). Data in, decision out.
            if _si.get("successfactors_failure_never_stage") and _is_sf \
                    and _kind == "sign_in":
                raise ValueError(
                    f"REFUSED — item #{iid}: a SuccessFactors sign-in "
                    f"never stages for the user (rules.yaml "
                    f"sign_in.successfactors_failure_path: SSO, then "
                    f"CREATE the tenant account with the saved "
                    f"SuccessFactors password — SuccessFactors "
                    f"accounts are per-tenant, so sign-in alone "
                    f"cannot work until it exists — verify by email "
                    f"in-flow, finish the application). Nothing was "
                    f"written.")
            # GUARD (the user, Nov 5, 2026 — Google #365): a sign-in stages
            # ONLY on a dead end proven in THIS run, attested by
            # signin_attempted: true — an earlier run's password
            # screen is stale evidence; profiles hold live sessions
            # (#365's step did not exist when finally driven).
            if _si.get("stage_requires_signin_attempted") \
                    and _kind == "sign_in" \
                    and not result.get("signin_attempted"):
                raise ValueError(
                    f"REFUSED — item #{iid}: a sign_in stage "
                    f"requires signin_attempted: true (rules.yaml "
                    f"sign_in.stage_requires_signin_attempted: "
                    f"re-drive the flow in THIS run first — the "
                    f"profile may already be signed in; stage only "
                    f"on a credential dead end proven now: no live "
                    f"session, no working SSO, no saved login). "
                    f"Nothing was written.")
            # GUARD (the user, Nov 5, 2026 — #392 Auger): a Gem resume
            # upload NEVER stages — the upload is impossible in this
            # browser for Muse and for the user alike (proven #180 Fetch,
            # #392 Auger); the run hands the user the manual packet.
            # GUARD (the user, Nov 6, 2026 — ALL accounts, generalizing
            # Workday + SuccessFactors in the same live session:
            # "as soon as you realize you can't login, go straight
            # to create account, use my workday credential"): a
            # sign-in stages ONLY when account creation was ALSO
            # attempted in this run and dead-ended, attested by
            # creation_attempted: true. On every portal, a failed
            # login goes straight to CREATE ACCOUNT with the Workday
            # credential — the user's one consistent vault password.
            if _si.get("stage_requires_creation_attempted") \
                    and _kind == "sign_in" \
                    and not result.get("creation_attempted"):
                raise ValueError(
                    f"REFUSED — item #{iid}: a sign_in stage "
                    f"requires creation_attempted: true (rules.yaml "
                    f"sign_in.create_account_on_login_failure: on "
                    f"EVERY portal, as soon as sign-in cannot get "
                    f"in, go straight to CREATE ACCOUNT in the same "
                    f"flow with the Workday credential — the user's one "
                    f"consistent password — verify by email in-flow "
                    f"and finish the application; if creation says "
                    f"the account exists, sign in with the same "
                    f"credential. Stage only when creation itself "
                    f"dead-ended in THIS run too). Nothing was "
                    f"written.")
            # GUARD (the user, Nov 6, 2026 — UKG #456 debug: "You should
            # try the password. No account. Sign up. Pop the
            # credential card and let me fill it."): when the run's
            # own classification says this portal has a PASSWORD
            # step (password_step: true — data, never prose), a
            # sign_in stage must attest the whole sequence ran: the
            # password was actually TRIED (holding at the form is
            # not an attempt), and at the point a password had to
            # be entered or set it was either filled from the vault
            # (saved_credential_filled) or the Secure Vault
            # credential card was popped for the user
            # (credential_card_offered). Parking before the card
            # is refused, on top of the signin_attempted +
            # creation_attempted guards above.
            if _si.get("stage_requires_sequence_on_password_step") \
                    and _kind == "sign_in" \
                    and result.get("password_step"):
                if not result.get("password_tried"):
                    raise ValueError(
                        f"REFUSED — item #{iid}: a password-step "
                        f"sign_in stage requires password_tried: "
                        f"true (rules.yaml sign_in."
                        f"password_step_sequence: TRY THE PASSWORD "
                        f"first — submit a sign-in with the saved "
                        f"one consistent credential; holding at the "
                        f"form without submitting is not an "
                        f"attempt). Nothing was written.")
                if not (result.get("saved_credential_filled")
                        or result.get("credential_card_offered")):
                    raise ValueError(
                        f"REFUSED — item #{iid}: a password-step "
                        f"sign_in stage requires "
                        f"saved_credential_filled: true or "
                        f"credential_card_offered: true (rules.yaml "
                        f"sign_in.password_step_sequence: when a "
                        f"password must be set and the credential "
                        f"service cannot fill the saved password "
                        f"on that host, POP THE SECURE VAULT "
                        f"CREDENTIAL CARD and let the user fill it — "
                        f"never park before the card). Nothing "
                        f"was written.")
            _gem = (self.rules.get("route_limits") or {}).get(
                "jobs.gem.com") or {}
            if _gem.get("manual_packet") and _is_gem \
                    and _kind == "resume_upload":
                raise ValueError(
                    f"REFUSED — item #{iid}: a Gem resume upload "
                    f"never stages for a tap session (rules.yaml "
                    f"route_limits jobs.gem.com: the upload is "
                    f"impossible in this browser for Muse and for "
                    f"the user alike — hand the user the manual packet: apply "
                    f"link, tailored resume, field values). Nothing "
                    f"was written.")
            entry = log_writer.append_entry(log_path, log_writer.staged(
                view, result.get("step", ""), result.get("blocker", "")))
            why = result.get("why")
            if why not in events_mod.WHY_CODES:
                why = events_mod.why_code(
                    f"{result.get('blocker', '')} {result.get('step', '')}")
            self._event("staged", st, it, source, why=why)
            return entry
        if outcome == "unstaged":
            # Return a staged / captcha item to the bench (audit fix,
            # Nov 4, 2026: the event type and rank existed; now the write
            # path does too). Rank ties staged/captcha, so the later
            # unstaged event supersedes the park on both sides.
            # GUARD (the user, Nov 4, 2026: "Yes add"): unstaging is the ONLY
            # door back to the bench, so the door checks who is knocking.
            # The check reads the item's whole history, not just its
            # head state — a limbo event is shadowed in the head by an
            # earlier staged at a higher rank (Fetch #180 reads "staged"
            # although the user's click made its outcome unknown), but the
            # uncertainty is real until verification or proof clears it:
            # - any submitted/verified event on either side → unstaged
            #   NEVER applies; refuse outright.
            # - any limbo event on either side (and no submission) →
            #   unstaged ONLY when the record carries a "proof" field —
            #   what was checked and what the portal said, showing the
            #   submission never landed — written into the log entry.
            # Staged/captcha items with no such history (never
            # submitted) unstage freely, as designed. A refusal raises
            # BEFORE anything is written, on either side.
            evs = events_mod.read_events(self.events_path)
            has_submitted = (it is not None and bool(it.events_of(
                "submitted"))) or any(
                    int(e.get("item") or -1) == iid
                    and e.get("type") in ("submitted", "verified")
                    for e in evs)
            has_limbo = (it is not None and bool(it.events_of(
                "limbo"))) or any(
                    int(e.get("item") or -1) == iid
                    and e.get("type") == "limbo" for e in evs)
            if has_submitted:
                raise ValueError(
                    f"REFUSED — item #{iid} has a submitted/verified "
                    f"event; unstaged never applies (nothing written)")
            if has_limbo:
                proof = (result.get("proof") or "").strip()
                if not proof:
                    raise ValueError(
                        f"REFUSED — item #{iid} has a limbo event (a "
                        f"submit whose outcome is unknown); unstaged "
                        f"requires a 'proof' field (what was checked "
                        f"and what the portal said) that the submission "
                        f"never landed (nothing written)")
                note = (result.get("note") or "").strip()
                result = {**result, "note":
                          (note + " | " if note else "")
                          + f"PROOF NEVER LANDED: {proof}"}
            entry = log_writer.append_entry(log_path, log_writer.unstaged(
                view, result.get("note", "")))
            self._event("unstaged", st, it, source)
            return entry
        if outcome == "captcha":
            # A captcha blocker is its OWN outcome: a `captcha` event (no
            # why — the type says it) and an AWAITING CAPTCHA TAKEOVER prose
            # entry. Never recorded as staged: taps are approvals the user grants,
            # a captcha is a bot-check she solves by taking the browser.
            # GUARD (the user, Nov 5, 2026 — #366 Allied/Paycom; rules.yaml
            # captcha_ip_block): a captcha that blocks this browser by
            # IP never parks for a takeover session — the run hands the user
            # a manual packet immediately (apply link + tailored
            # resume + field values) and the record must say so
            # (manual_packet: true). Whether the block is an IP block
            # is a JUDGMENT the run (the LLM — it watched the puzzle
            # refuse this browser) sends as DATA: ip_blocked: true.
            # The code checks the flag, never the note's wording
            # (the user, Nov 5, 2026: no hardcoded keyword parsing). Lever
            # captchas are excluded: they follow the route_limits
            # packet rule, enforced in next_order / the Lever branch
            # of the work order, not here. Refuse BEFORE writing.
            _ipb = self.rules.get("captcha_ip_block") or {}
            if _ipb.get("manual_packet_immediately") \
                    and result.get("ip_blocked") \
                    and not result.get("manual_packet"):
                raise ValueError(
                    f"REFUSED — item #{iid}: a captcha flagged "
                    f"ip_blocked: true never parks for a session "
                    f"(rules.yaml captcha_ip_block: hand the user the "
                    f"manual packet immediately — apply link, "
                    f"tailored resume, field values — and record "
                    f"with manual_packet: true). Nothing was "
                    f"written.")
            # GUARD (the user, Nov 6, 2026: "Add rippling to manual
            # packet group" — #435 Reserv: the Cloudflare check
            # expired twice in this browser, then FAILED on the user's
            # own takeover solve): a Rippling-host item never parks
            # for a captcha session or a takeover window — it goes
            # to the user as a manual packet. Route host/ATS are DATA
            # from the item's stocked route, never prose.
            _rip = (self.rules.get("route_limits") or {}).get(
                "ats.rippling.com") or {}
            if _rip.get("manual_packet") \
                    and not result.get("manual_packet"):
                try:
                    _rroute, _rsal = self._route_and_salary(st, it)
                    _rhost = urlparse(_rroute.get("url") or "").netloc
                    _rats = _rroute.get("ats") or ""
                except Exception:
                    _rhost, _rats = "", ""
                if _rhost == "rippling.com" \
                        or _rhost.endswith(".rippling.com") \
                        or _rats == "Rippling":
                    raise ValueError(
                        f"REFUSED — item #{iid}: Rippling is a "
                        f"manual-packet host (rules.yaml "
                        f"route_limits ats.rippling.com — the user, "
                        f"Nov 6, 2026): its Cloudflare check cannot "
                        f"pass in this browser (proven #435 Reserv: "
                        f"expired twice, then failed on the user's own "
                        f"solve). Hand the user the manual packet — apply "
                        f"link, tailored resume, field values — "
                        f"and record with manual_packet: true. "
                        f"Nothing was written.")
            entry = log_writer.append_entry(log_path, log_writer.captcha(
                view, result.get("step", ""), result.get("note", "")))
            self._event("captcha", st, it, source)
            return entry
        if outcome == "manual_packet":
            # A MANUAL PACKET (the user, Nov 6, 2026) is its own outcome: a
            # `packet` event (no why — the type says it) and a MANUAL
            # PACKET prose entry. It supersedes the item's captcha /
            # staged park at the same rank, on both sides. The item
            # leaves the piles only when the user reports her own-device
            # submission and the run records outcome "submitted".
            if not (result.get("step") or "").strip():
                raise ValueError(
                    f"REFUSED — item #{iid}: a manual_packet record "
                    f"must name its step (why this browser cannot "
                    f"finish it: Lever / Gem / IP-blocked captcha). "
                    f"Nothing was written.")
            entry = log_writer.append_entry(
                log_path, log_writer.manual_packet(
                    view, result.get("portal", ""),
                    result.get("step", ""), result.get("note", "")))
            self._event("packet", st, it, source)
            return entry
        if outcome == "skipped":
            entry = log_writer.append_entry(log_path, log_writer.skipped(
                view, result.get("reason", "skipped by program precondition")))
            why = result.get("why")
            if why not in events_mod.WHY_CODES:
                why = events_mod.why_code(result.get("reason", ""))
            self._event("skipped", st, it, source, why=why)
            return entry
        if outcome == "limbo":
            entry = log_writer.append_entry(log_path, log_writer.limbo(
                view, result.get("note", "outcome uncertain")))
            self._event("limbo", st, it, source)
            # Fix (b), Nov 4, 2026: a limbo item joins the verify queue
            # exactly like a submitted one, so the code's +10/+30 Gmail
            # checks (watcher Step 5 drain) watch it too — before this,
            # only the prose hourly scan watched a takeover-click limbo
            # (Fetch #180 was never enqueued).
            self._enqueue_verify(iid, view["company"])
            return entry
        if outcome == "post_submit_pending":
            # NOTE: the design's event-type list has no post-submit-pending
            # type, so this outcome is prose-only for now (flagged in the
            # events-layer report, Nov 4, 2026).
            return log_writer.append_entry(
                log_path, log_writer.post_submit_pending(
                    view, result.get("note", "validation code demanded after submit")))
        if outcome == "friction":
            # Lane scope (the user, Nov 7, 2026): a friction signal on a
            # LinkedIn-sourced item stops the LinkedIn lane only —
            # the external sources (Jobright, and Indeed since
            # Nov 12, 2026) carry on. Any other source is a full stop.
            # LINKEDIN_ALERT (the user, Nov 12, 2026): a friction signal on
            # an alert-sourced item is a LinkedIn-platform signal —
            # scope "linkedin" — but it ALSO pauses the alert lane
            # (alert_lane_blocked marker): a fresh warning/checkpoint
            # served during alert Easy Apply work stops that work
            # and alerts the user, while the external sources carry on.
            _src_up = (source or "").upper()
            _fscope = ("linkedin" if _src_up in ("LINKEDIN",
                                                 "LINKEDIN_ALERT")
                       else "all")
            self.set_friction(result.get("signal", "friction reported"),
                              iid, scope=_fscope,
                              alert_lane_blocked=(
                                  _src_up == "LINKEDIN_ALERT"))
            entry = log_writer.append_entry(log_path, log_writer.friction(
                view, result.get("signal", "friction reported")))
            # friction_set is a window-level signal: no src on the event.
            self._event("friction_set", st, it, source, with_src=False)
            return entry
        if outcome == "exception":
            # Prose-only, like post_submit_pending: no matching event type.
            return log_writer.append_entry(
                log_path,
                f"EXCEPTION — #{iid} {view['company']}, {view['role']}: "
                f"{result.get('detail', 'handed to Muse with full context')} "
                f"(Recorded by spine program.)")
        raise ValueError(f"unknown outcome: {outcome}")

    # outcome -> the event type record() writes for it (None = the
    # outcome is prose-only by design).
    _RECORD_EVENT_TYPE = {
        "submitted": "submitted", "email_verified": "verified",
        "staged": "staged", "unstaged": "unstaged", "captcha": "captcha",
        "manual_packet": "packet",
        "skipped": "skipped", "limbo": "limbo", "friction": "friction_set",
        "post_submit_pending": None, "exception": None,
    }

    # Every event type that SETTLES or PARKS an item — the outcome
    # types record() writes. Used by the duplicate guard: an item
    # with any of these in the event book has a completed program
    # outcome on file; only a prose-only outcome (no book twin) can
    # be the half-completed write the guard refuses. friction_set IS
    # included on purpose: record() writes it WITH the item id (the
    # friction branch passes the item), so its presence proves a
    # record() call for this item completed both writes — a prose
    # outcome older than it is migration history, not a replay. (An
    # earlier draft excluded it, and the fake round-trip item #142 —
    # dozens of friction_set events, no outcome — was misread.)
    _OUTCOME_EVENT_TYPES = frozenset(
        t for t in _RECORD_EVENT_TYPE.values() if t is not None)

    def record_with_check(self, result: dict,
                          log_path: str | None = None) -> dict:
        """record() + THE HANDOFF CHECK (the user, Nov 5, 2026 — Muse and
        the program must fully understand what the other handed off).
        Runs record(), then READS BOTH RECORDS BACK: the prose entry
        must be present byte-for-byte in the log, and the event book's
        latest event for the item must be the type this outcome writes
        (which also exposes the why code the program DERIVED when the
        caller didn't supply one — no silent interpretation). Returns
        {"entry", "understood", "landed_as", "verified", "problems"}:
        verified is true only when both sides landed as handed over."""
        log_path = log_path or self.log_path
        entry = self.record(result, log_path=log_path)
        iid = int(result["item_id"])
        outcome = result["outcome"]
        understood = {"item_id": iid, "outcome": outcome,
                      "fields": {k: v for k, v in result.items()
                                 if k not in ("item_id", "outcome")}}
        problems: list[str] = []
        raw = Path(log_path).read_text(encoding="utf-8")
        prose_landed = entry in raw
        if not prose_landed:
            problems.append("the written log entry is not in the log "
                            "on read-back")
        expected = self._RECORD_EVENT_TYPE.get(outcome)
        landed_event = None
        if expected is not None:
            evs = [e for e in events_mod.read_events(self.events_path)
                   if int(e.get("item") or -1) == iid]
            last = evs[-1] if evs else None
            if last is not None:
                landed_event = {"type": last.get("type"),
                                "why": last.get("why"),
                                "src": last.get("src"),
                                "win": last.get("win")}
            if landed_event is None or landed_event["type"] != expected:
                problems.append(
                    f"the program's record holds "
                    f"{landed_event['type'] if landed_event else 'no event'} "
                    f"for #{iid}, expected {expected}")
        # TRACK FILE (the user, Nov 6, 2026): every recorded outcome rebuilds
        # state/open_piles.json, so the captcha + manual-packet piles
        # The user still has to do herself are always listed in one file.
        # A rebuild failure is reported on the result, never silent —
        # and never re-marks the handoff itself unverified: the two
        # records above are what "verified" judges.
        piles_note = "rebuilt"
        try:
            self._write_piles_file()
        except Exception as exc:  # surfaced, not swallowed
            piles_note = f"FAILED: {exc}"
        return {"entry": entry, "understood": understood,
                "landed_as": {"prose_entry_in_log": prose_landed,
                              "event": landed_event},
                "verified": not problems, "problems": problems,
                "piles_file": piles_note}
