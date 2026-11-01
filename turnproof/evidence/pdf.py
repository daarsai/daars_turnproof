"""One-page-ish PDF rendering of an evidence packet for people who will not open JSON.

The PDF is a human-readable VIEW. The signed JSON packet remains the record; the PDF prints
the packet hash and signature key so a reader can verify the JSON independently.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

NAVY = (11, 37, 69)
ORANGE = (242, 107, 29)
GREY = (90, 90, 90)


def _fmt_min(v) -> str:
    return "n/a" if v is None else f"{v} min"


def render_packet_pdf(packet: dict, run_dir: Path, out_path: Path) -> Path:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 9, "TurnProof evidence packet", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GREY)
    pdf.cell(
        0, 5, f"{packet['packet_id']}  |  {packet['data_label']}", new_x="LMARGIN", new_y="NEXT"
    )
    pdf.ln(2)

    f = packet["flight"]
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    rows = [
        ("Flight", f"{f['number']}  {f['date']}  ({f['airline']})"),
        ("Station / stand", f"{packet['station']} / {packet['stand']}"),
        ("Handler", packet["parties"]["handler"]),
        (
            "Camera / clip",
            f"{packet['source']['camera_id']}  sha256 {packet['source']['file_sha256'][:16]}...",
        ),
        ("Time sync", packet["time_sync"]["method"]),
    ]
    for k, v in rows:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(38, 6, k)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, v, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    def heading(txt: str) -> None:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*ORANGE)
        pdf.cell(0, 8, txt, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 10)

    heading("Claim vs video")
    c, p = packet["airline_claim"], packet["proposed_claim"]
    pdf.cell(0, 6, f"Airline claim: code {c['delay_code']}, {c['minutes']} min ({c['source']})",
             new_x="LMARGIN", new_y="NEXT")  # fmt: skip
    pdf.cell(0, 6, f"Video-supported: code family {p['delay_code_family']}, "
             f"{_fmt_min(p['minutes_supported_by_video'])}", new_x="LMARGIN", new_y="NEXT")  # fmt: skip
    pdf.multi_cell(0, 6, f"Basis: {p['basis']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    rv = packet.get("review") or {}
    hs = packet.get("human_statement")
    if rv.get("decision", "pending") != "pending" or hs:
        heading("Handler review")
        if rv.get("decision", "pending") != "pending":
            pdf.multi_cell(0, 6, f"Decision: {rv['decision']} by {rv.get('operator')} at {rv.get('t_utc')}"
                           + (f" - note: {rv['note']}" if rv.get("note") else ""),
                           new_x="LMARGIN", new_y="NEXT")  # fmt: skip
        if hs:
            src = (
                f"spoken, transcribed by {hs.get('model')}"
                if hs.get("source") == "spoken"
                else "typed"
            )
            pdf.multi_cell(0, 6, f"Operator statement ({src}): \"{hs.get('text', '')}\"",
                           new_x="LMARGIN", new_y="NEXT")  # fmt: skip
        cp = packet.get("counterparty") or {}
        if cp.get("state", "PENDING") != "PENDING":
            pdf.multi_cell(0, 6, f"Airline: {cp['state']} by {cp.get('actor')} at {cp.get('t_utc')}"
                           + (f" - {cp['reason']}" if cp.get("reason") else ""),
                           new_x="LMARGIN", new_y="NEXT")  # fmt: skip
        pdf.ln(1)

    heading("Milestones (from video)")
    for m in packet["milestones"]:
        how = "rule" if m["method"].startswith("sam31") else "spark"
        if "present_at_clip_start" in m["method"]:
            how += ", present at clip start"
        if "cut_short" in m["method"]:
            how += ", cut short by clip end"
        line = (
            f"{m['name']:<22} {m['t_utc'] or 'unsynced':<26} frame {m['frame_index']:<6} "
            f"conf {m['confidence']:.2f}  [{how}]"
        )
        pdf.set_font("Courier", "", 8.5)
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.ln(1)

    heading("Discrepancy table")
    pdf.set_font("Courier", "", 8.5)
    pdf.cell(0, 5, f"{'milestone':<22}{'video (UTC)':<26}{'handler log (UTC)':<22}{'delta min':<10}",
             new_x="LMARGIN", new_y="NEXT")  # fmt: skip
    for r in packet["discrepancies"]:
        d = "" if r["video_minus_log_min"] is None else f"{r['video_minus_log_min']:+.1f}"
        pdf.cell(
            0, 5,
            f"{r['milestone']:<22}{(r['video_utc'] or '-'):<26}{(r['handler_log_utc'] or '-'):<22}{d:<10}",
            new_x="LMARGIN", new_y="NEXT",
        )  # fmt: skip
        if r.get("note"):
            pdf.set_font("Courier", "I", 8)
            pdf.multi_cell(0, 4.5, f"    note: {r['note']}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Courier", "", 8.5)
    pdf.set_font("Helvetica", "", 10)
    pdf.ln(1)

    if packet.get("observed_facts"):
        heading("Keyframe facts (Muse Spark; flags only, never decides)")
        for fact in packet["observed_facts"]:
            pdf.multi_cell(0, 5.5, f"- {fact['text']}  (frames {', '.join(fact['frames'])})",
                           new_x="LMARGIN", new_y="NEXT")  # fmt: skip
        pdf.ln(1)

    heading("Evidence frames (redacted; persons blurred)")
    imgs = [
        run_dir / "display" / f"{e['id']}_overlay.png"
        if (run_dir / "display" / f"{e['id']}_overlay.png").exists()
        else run_dir / "display" / f"{e['id']}.png"
        for e in packet["evidence_frames"]
    ]
    x, y0, w = pdf.l_margin, pdf.get_y(), 58
    for e, img in zip(packet["evidence_frames"], imgs, strict=True):
        if not img.exists():
            continue
        if x + w > pdf.w - pdf.r_margin:
            x = pdf.l_margin
            y0 += 32
        if y0 + 32 > pdf.h - pdf.b_margin:
            pdf.add_page()
            y0 = pdf.get_y()
        pdf.image(str(img), x=x, y=y0, w=w)
        pdf.set_xy(x, y0 + 24)
        pdf.set_font("Courier", "", 6.5)
        pdf.multi_cell(w, 3, f"{e['id']} {e['t_utc'] or 'unsynced'}\nsha256 {e['sha256_redacted'][:24]}...",
                       new_x="RIGHT", new_y="TOP")  # fmt: skip
        x += w + 4
    pdf.set_xy(pdf.l_margin, y0 + 34)
    pdf.set_font("Helvetica", "", 10)

    heading("Integrity")
    pdf.set_font("Courier", "", 8)
    pdf.multi_cell(
        0, 4.5, f"packet_sha256  {packet['packet_sha256']}", new_x="LMARGIN", new_y="NEXT"
    )
    s = packet["signature"]
    pdf.multi_cell(
        0, 4.5, f"signature      {s['alg']} key_id={s['key_id']}", new_x="LMARGIN", new_y="NEXT"
    )
    pdf.multi_cell(0, 4.5, f"event log head {packet['chain']['event_log_head_sha256']}",
                   new_x="LMARGIN", new_y="NEXT")  # fmt: skip
    pdf.set_font("Helvetica", "I", 8.5)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(
        0, 4.5,
        "Verify the JSON packet independently:  python verify_packet.py <packet.json> "
        "--frames <display dir> --log <eventlog.jsonl>.  This PDF is a view of the signed packet, "
        "not the record itself.",
        new_x="LMARGIN", new_y="NEXT",
    )  # fmt: skip
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
