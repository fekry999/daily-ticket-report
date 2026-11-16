import os
import io
import html
import sys
import smtplib
import requests
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from dotenv import load_dotenv

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    HRFlowable,
)

# =====================================================
# CONFIGURATION
# =====================================================

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")

DATA_SOURCE_ID = (
    os.environ.get("NOTION_DATA_SOURCE_ID", "").strip()
    or "419cb32b-5aa2-8005-b004-000b721de702"
)

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")

GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

REPORT_RECEIVER = (
    os.environ.get("REPORT_RECEIVER", "").strip()
    or "fekryosama999@gmail.com"
)

TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

DATE_COL = (
    os.environ.get("DATE_COL", "").strip()
    or "Reported Date & Time"
)

DESC_COL = (
    os.environ.get("DESC_COL", "").strip()
    or "Description"
)

OUT = str(BASE_DIR / "report.pdf")

DAYS_BACK = 1

NOTION_VERSION = "2025-09-03"


# =====================================================
# THEME
# =====================================================

NAVY = "#1e1b4b"
INDIGO = "#6366f1"
SLATE = "#475569"
MUTED = "#94a3b8"
LIGHT_BG = "#eef2ff"
ROW_ALT = "#f8fafc"
LINE = "#e2e8f0"

STATUS_COLORS = {
    "solved": "#16a34a",
    "pending": "#d97706",
    "in progress": "#2563eb",
    "open": "#2563eb",
    "closed": "#16a34a",
}

PRIORITY_COLORS = {
    "critical": "#b91c1c",
    "high": "#ef4444",
    "medium": "#f59e0b",
    "low": "#22c55e",
}

PRIORITY_ORDER = ["critical", "high", "medium", "low"]


def status_color(name):
    return STATUS_COLORS.get(str(name).strip().lower(), SLATE)


def priority_color(name):
    return PRIORITY_COLORS.get(str(name).strip().lower(), SLATE)


# =====================================================
# NOTION API
# =====================================================

def fetch_page_text(page_id, headers, limit=300):
    """Fallback: read description from the page body."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=50"

    r = requests.get(url, headers=headers, timeout=60)

    if not r.ok:
        return ""

    parts = []

    for block in r.json().get("results", []):
        btype = block.get("type")
        rich = block.get(btype, {}).get("rich_text", [])
        text = "".join(t.get("plain_text", "") for t in rich)
        if text:
            parts.append(text)

    return " ".join(parts)[:limit]


def fetch():

    if not NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN is missing.")

    if not DATA_SOURCE_ID:
        raise ValueError("NOTION_DATA_SOURCE_ID is missing.")

    if not DATE_COL:
        raise ValueError("DATE_COL is missing.")

    print(f"Using data source: {DATA_SOURCE_ID}")
    print(f"Using date property: [{DATE_COL}]")
    print(f"Using description property: [{DESC_COL}]")

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }

    since = (
        datetime.now(timezone.utc)
        - timedelta(days=DAYS_BACK)
    ).isoformat()

    rows = []
    cursor = None

    url = (
        f"https://api.notion.com/v1/"
        f"data_sources/{DATA_SOURCE_ID}/query"
    )

    with requests.Session() as session:

        while True:

            body = {
                "page_size": 100,

                "filter": {
                    "property": DATE_COL,
                    "date": {
                        "on_or_after": since
                    }
                }
            }

            if cursor:
                body["start_cursor"] = cursor

            response = session.post(
                url,
                headers=headers,
                json=body,
                timeout=60
            )

            if not response.ok:
                raise RuntimeError(
                    f"Notion API Error: {response.status_code}\n"
                    f"{response.text}"
                )

            data = response.json()

            page_results = data.get("results", [])

            rows.extend(page_results)

            print(
                f"Fetched page with {len(page_results)} tickets; "
                f"total so far: {len(rows)}"
            )

            if not data.get("has_more"):
                break

            cursor = data.get("next_cursor")

            if not cursor:
                break

    tickets = []

    for page in rows:
        ticket = flat(page)

        if not ticket.get(DESC_COL):
            ticket[DESC_COL] = fetch_page_text(page["id"], headers)

        tickets.append(ticket)

    print(f"Fetched {len(tickets)} tickets from Notion.")

    return tickets


# =====================================================
# FLATTEN NOTION DATA
# =====================================================

def flat(page):

    result = {}

    for key, prop in page.get("properties", {}).items():

        prop_type = prop.get("type")
        value = prop.get(prop_type)

        if value is None:
            result[key] = ""
            continue

        if prop_type in ("title", "rich_text"):

            result[key] = "".join(
                item.get("plain_text", "")
                for item in value
            )

        elif prop_type in ("select", "status"):

            result[key] = (
                value.get("name", "")
                if value else ""
            )

        elif prop_type == "multi_select":

            result[key] = ", ".join(
                item.get("name", "")
                for item in value
            )

        elif prop_type == "date":

            result[key] = (
                value.get("start", "")
                if value else ""
            )

        elif prop_type == "people":

            result[key] = ", ".join(
                item.get("name")
                or item.get("person", {}).get("email", "")
                or ""
                for item in value
            )

        elif prop_type == "number":

            result[key] = value

        elif prop_type == "checkbox":

            result[key] = value

        elif prop_type in ("url", "email", "phone_number"):

            result[key] = value or ""

        elif prop_type == "unique_id":

            prefix = value.get("prefix") or ""
            number = value.get("number", "")

            result[key] = f"{prefix}{number}"

        elif prop_type == "formula":

            formula_type = value.get("type")
            result[key] = value.get(formula_type, "")

        elif prop_type in ("created_time", "last_edited_time"):

            result[key] = value

        else:

            result[key] = ""

    return result


# =====================================================
# CHARTS
# =====================================================

def charts(by_status, by_prio):

    fig, ax = plt.subplots(
        1,
        2,
        figsize=(9.5, 3.4),
        gridspec_kw={"width_ratios": [1.15, 1]}
    )

    total = sum(by_status.values())

    # ---------- Donut: status ----------

    if by_status:

        labels = list(by_status.keys())
        values = list(by_status.values())
        slice_colors = [status_color(label) for label in labels]

        wedges, _, autotexts = ax[0].pie(
            values,
            colors=slice_colors,
            startangle=90,
            counterclock=False,
            autopct=lambda p: f"{p:.0f}%" if p >= 5 else "",
            pctdistance=0.775,
            wedgeprops=dict(
                width=0.45,
                edgecolor="white",
                linewidth=2
            ),
            textprops=dict(
                color="white",
                fontsize=9,
                fontweight="bold"
            )
        )

        ax[0].text(
            0, 0.07,
            str(total),
            ha="center",
            va="center",
            fontsize=22,
            fontweight="bold",
            color=NAVY
        )

        ax[0].text(
            0, -0.2,
            "tickets",
            ha="center",
            va="center",
            fontsize=8,
            color=MUTED
        )

        ax[0].legend(
            wedges,
            [f"{l}  ({v})" for l, v in zip(labels, values)],
            loc="center left",
            bbox_to_anchor=(1.0, 0.5),
            frameon=False,
            fontsize=8
        )

    else:

        ax[0].text(
            0.5, 0.5,
            "No data",
            ha="center",
            va="center",
            color=MUTED
        )

        ax[0].axis("off")

    ax[0].set_title(
        "By Status",
        fontsize=11,
        fontweight="bold",
        color=NAVY,
        pad=10
    )

    # ---------- Bars: priority ----------

    ordered = sorted(
        by_prio.items(),
        key=lambda item: (
            PRIORITY_ORDER.index(item[0].strip().lower())
            if item[0].strip().lower() in PRIORITY_ORDER
            else len(PRIORITY_ORDER)
        )
    )

    names = [name for name, _ in ordered] or [""]
    counts = [count for _, count in ordered] or [0]

    bars = ax[1].bar(
        names,
        counts,
        color=[priority_color(n) for n in names],
        width=0.5
    )

    ax[1].bar_label(
        bars,
        padding=3,
        fontsize=9,
        fontweight="bold",
        color=NAVY
    )

    ax[1].set_ylim(0, max(counts) * 1.25 if max(counts) else 1)
    ax[1].yaxis.set_major_locator(MaxNLocator(integer=True))
    ax[1].yaxis.grid(True, color=LINE, linewidth=0.8)
    ax[1].set_axisbelow(True)

    ax[1].set_title(
        "By Priority",
        fontsize=11,
        fontweight="bold",
        color=NAVY,
        pad=10
    )

    ax[1].tick_params(colors=SLATE, labelsize=8, length=0)

    for side in ("top", "right", "left"):
        ax[1].spines[side].set_visible(False)

    ax[1].spines["bottom"].set_color(LINE)

    fig.tight_layout(w_pad=3)

    buffer = io.BytesIO()

    fig.savefig(
        buffer,
        format="png",
        dpi=170,
        bbox_inches="tight"
    )

    plt.close(fig)

    buffer.seek(0)

    return buffer


# =====================================================
# PDF HELPERS
# =====================================================

def draw_footer(canvas, doc):

    canvas.saveState()

    canvas.setStrokeColor(colors.HexColor(LINE))
    canvas.setLineWidth(0.5)
    canvas.line(1.5 * cm, 1.3 * cm, A4[0] - 1.5 * cm, 1.3 * cm)

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor(MUTED))

    canvas.drawString(1.5 * cm, 0.8 * cm, "Tickets Tracker Report")

    canvas.drawRightString(
        A4[0] - 1.5 * cm,
        0.8 * cm,
        f"Page {doc.page}"
    )

    canvas.restoreState()


# =====================================================
# PDF REPORT
# =====================================================

def build_pdf(
    tickets,
    out=OUT,
    title="Tickets Report - Last 24 Hours",
    subtitle="Tickets reported during the last 24 hours."
):

    total = len(tickets)

    by_status = Counter(
        t.get("Status") or "N/A"
        for t in tickets
    )

    by_prio = Counter(
        t.get("Priority") or "N/A"
        for t in tickets
    )

    solved = sum(
        count
        for status, count in by_status.items()
        if status.strip().lower() == "solved"
    )

    pending = sum(
        count
        for status, count in by_status.items()
        if status.strip().lower() == "pending"
    )

    rate = round(
        solved * 100 / total
    ) if total else 0

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=colors.HexColor(NAVY),
        alignment=TA_CENTER,
        spaceAfter=4
    )

    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor(MUTED),
        alignment=TA_CENTER
    )

    cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#0f172a"),
        wordWrap="CJK"
    )

    header_cell = ParagraphStyle(
        "TableHeader",
        parent=cell,
        textColor=colors.white,
        fontName="Helvetica-Bold",
        fontSize=8
    )

    story = []

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    story.append(Paragraph(title, title_style))

    story.append(
        Paragraph(
            f"{subtitle}  |  Generated: {generated}",
            subtitle_style
        )
    )

    story.append(Spacer(1, 8))

    story.append(
        HRFlowable(
            width="100%",
            thickness=1.2,
            color=colors.HexColor(INDIGO),
            spaceAfter=12
        )
    )

    # ---------- KPI cards ----------

    kpi = Table(
        [
            ["TOTAL", "SOLVED", "PENDING", "SOLVE RATE"],
            [total, solved, pending, f"{rate}%"]
        ],
        colWidths=[4.5 * cm] * 4,
        rowHeights=[0.8 * cm, 1.8 * cm]
    )

    kpi.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor(LIGHT_BG)),
            ("FONTSIZE", (0, 1), (-1, 1), 22),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 1), (0, 1), colors.HexColor(NAVY)),
            ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor("#16a34a")),
            ("TEXTCOLOR", (2, 1), (2, 1), colors.HexColor("#d97706")),
            ("TEXTCOLOR", (3, 1), (3, 1), colors.HexColor(INDIGO)),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEAFTER", (0, 0), (-2, -1), 4, colors.white),
        ])
    )

    story.append(kpi)
    story.append(Spacer(1, 14))

    # ---------- Charts ----------

    chart_buffer = charts(by_status, by_prio)

    img_w, img_h = ImageReader(chart_buffer).getSize()
    chart_buffer.seek(0)

    chart_width = 16.5 * cm
    chart_height = chart_width * img_h / img_w

    story.append(
        Image(
            chart_buffer,
            width=chart_width,
            height=chart_height
        )
    )

    story.append(Spacer(1, 14))

    # ---------- Tickets table ----------

    if not tickets:

        story.append(
            Paragraph(
                "No tickets found during the last 24 hours.",
                subtitle_style
            )
        )

    else:

        data = [[
            Paragraph("Ticket", header_cell),
            Paragraph("Title", header_cell),
            Paragraph("Description", header_cell),
            Paragraph("Status", header_cell),
            Paragraph("Priority", header_cell),
            Paragraph("Reported", header_cell),
        ]]

        for ticket in tickets:

            ticket_number = str(ticket.get("Ticket Number", ""))
            ticket_title = str(ticket.get("Ticket Title", ""))
            description = str(ticket.get(DESC_COL, "") or "-")

            if len(description) > 300:
                description = description[:300].rstrip() + "..."

            status = str(ticket.get("Status", "")) or "-"
            priority = str(ticket.get("Priority", "")) or "-"
            reported = str(ticket.get(DATE_COL, ""))

            data.append([
                Paragraph(
                    f"<b>{html.escape(ticket_number)}</b>",
                    cell
                ),
                Paragraph(html.escape(ticket_title), cell),
                Paragraph(
                    html.escape(description).replace("\n", "<br/>"),
                    cell
                ),
                Paragraph(
                    f'<font color="{status_color(status)}">'
                    f"<b>{html.escape(status)}</b></font>",
                    cell
                ),
                Paragraph(
                    f'<font color="{priority_color(priority)}">'
                    f"<b>{html.escape(priority)}</b></font>",
                    cell
                ),
                Paragraph(html.escape(reported[:10] or "-"), cell),
            ])

        table = Table(
            data,
            colWidths=[
                2.6 * cm,   # Ticket
                3.8 * cm,   # Title
                6.2 * cm,   # Description
                1.8 * cm,   # Status
                1.7 * cm,   # Priority
                1.9 * cm,   # Reported
            ],
            repeatRows=1
        )

        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                    colors.white,
                    colors.HexColor(ROW_ALT)
                ]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 1), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
            ])
        )

        story.append(table)

    document = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.8 * cm
    )

    document.build(
        story,
        onFirstPage=draw_footer,
        onLaterPages=draw_footer
    )

    return total, solved, pending, rate


# =====================================================
# GMAIL
# =====================================================

def send_gmail():

    if not GMAIL_ADDRESS:
        raise ValueError("GMAIL_ADDRESS is missing.")

    if not GMAIL_APP_PASSWORD:
        raise ValueError("GMAIL_APP_PASSWORD is missing.")

    if not REPORT_RECEIVER:
        raise ValueError("REPORT_RECEIVER is missing.")

    if not os.path.exists(OUT):
        raise FileNotFoundError(f"PDF file not found: {OUT}")

    message = EmailMessage()

    message["Subject"] = "Tickets Report - Last 24 Hours"
    message["From"] = GMAIL_ADDRESS
    message["To"] = REPORT_RECEIVER

    message.set_content(
        "Hello,\n\n"
        "Please find attached the latest Tickets Report.\n"
    )

    with open(OUT, "rb") as pdf_file:

        message.add_attachment(
            pdf_file.read(),
            maintype="application",
            subtype="pdf",
            filename="report.pdf"
        )

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
        timeout=60
    ) as smtp:

        smtp.login(
            GMAIL_ADDRESS,
            GMAIL_APP_PASSWORD.replace(" ", "")
        )

        smtp.send_message(message)

    print(
        f"PDF emailed successfully to {REPORT_RECEIVER}."
    )


# =====================================================
# TELEGRAM
# =====================================================

def send_telegram(total, solved, pending, rate):

    if not TG_TOKEN or not TG_CHAT_ID:

        print("Telegram is not configured. Skipping.")

        return

    url = (
        f"https://api.telegram.org/"
        f"bot{TG_TOKEN}/sendDocument"
    )

    caption = (
        f"Tickets Report - Last 24 Hours\n"
        f"Total: {total}\n"
        f"Solved: {solved}\n"
        f"Pending: {pending}\n"
        f"Solve Rate: {rate}%"
    )

    with open(OUT, "rb") as file:

        response = requests.post(
            url,
            data={
                "chat_id": TG_CHAT_ID,
                "caption": caption
            },
            files={
                "document": file
            },
            timeout=60
        )

    if not response.ok:

        raise RuntimeError(
            f"Telegram Error: {response.status_code}\n"
            f"{response.text}"
        )

    print("PDF sent to Telegram successfully.")


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":

    try:

        print("=" * 50)
        print("TICKETS REPORT - LAST 24 HOURS")
        print("=" * 50)

        tickets = fetch()

        total, solved, pending, rate = build_pdf(
            tickets,
            title="Tickets Report - Last 24 Hours",
            subtitle="Tickets reported during the last 24 hours."
        )

        print("\nREPORT SUMMARY")
        print("-" * 30)

        print(f"Total tickets : {total}")
        print(f"Solved        : {solved}")
        print(f"Pending       : {pending}")
        print(f"Solve rate    : {rate}%")

        print("-" * 30)

        print(f"\nPDF generated successfully: {OUT}")

        send_gmail()

        send_telegram(
            total,
            solved,
            pending,
            rate
        )

    except Exception as error:

        print("\nERROR:")
        print(error)

        sys.exit(1)