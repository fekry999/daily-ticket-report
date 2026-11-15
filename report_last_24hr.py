
import os
import io
import html
import sys
import smtplib
import requests
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from dotenv import load_dotenv

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
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

OUT = str(BASE_DIR / "report.pdf")

DAYS_BACK = 1

NOTION_VERSION = "2025-09-03"


# =====================================================
# NOTION API
# =====================================================

def fetch():

    if not NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN is missing.")

    if not DATA_SOURCE_ID:
        raise ValueError("NOTION_DATA_SOURCE_ID is missing.")

    if not DATE_COL:
        raise ValueError("DATE_COL is missing.")

    print(f"Using data source: {DATA_SOURCE_ID}")
    print(f"Using date property: [{DATE_COL}]")

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

    tickets = [flat(page) for page in rows]

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

def charts(by_status, by_prio, by_who):

    fig, ax = plt.subplots(
        1,
        3,
        figsize=(11, 3.2)
    )

    palette = [
        "#6366f1",
        "#22c55e",
        "#f59e0b",
        "#ef4444",
        "#06b6d4",
        "#a855f7",
    ]

    if by_status:

        ax[0].pie(
            by_status.values(),
            labels=by_status.keys(),
            colors=palette,
            autopct="%1.0f%%",
            wedgeprops=dict(width=0.45)
        )

    else:

        ax[0].text(
            0.5, 0.5,
            "No data",
            ha="center",
            va="center"
        )

    ax[0].set_title("By Status")

    priorities = list(by_prio.keys())
    priority_counts = list(by_prio.values())

    ax[1].bar(
        priorities or [""],
        priority_counts or [0],
        color=palette
    )

    ax[1].set_title("By Priority")

    top = by_who.most_common(6)[::-1]

    ax[2].barh(
        [name for name, count in top] or [""],
        [count for name, count in top] or [0],
        color="#6366f1"
    )

    ax[2].set_title("By Reporter")

    for axis in ax[1:]:

        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    fig.tight_layout()

    buffer = io.BytesIO()

    fig.savefig(
        buffer,
        format="png",
        dpi=150,
        bbox_inches="tight"
    )

    plt.close(fig)

    buffer.seek(0)

    return buffer


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

    by_who = Counter(
        t.get("Reported by") or "N/A"
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

    cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontSize=7,
        leading=9,
        wordWrap="CJK"
    )

    header_cell = ParagraphStyle(
        "TableHeader",
        parent=cell,
        textColor=colors.white,
        fontName="Helvetica-Bold"
    )

    story = []

    generated = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    story.append(
        Paragraph(
            title,
            styles["Title"]
        )
    )

    story.append(
        Paragraph(
            f"{subtitle} Generated: {generated}",
            styles["Normal"]
        )
    )

    story.append(Spacer(1, 12))

    kpi = Table(
        [
            ["TOTAL", "SOLVED", "PENDING", "SOLVE RATE"],
            [
                total,
                solved,
                pending,
                f"{rate}%"
            ]
        ],
        colWidths=[4.4 * cm] * 4
    )

    kpi.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e1b4b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#eef2ff")),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, 1), 22),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 1), (-1, 1), 10),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
            ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor("#16a34a")),
            ("TEXTCOLOR", (2, 1), (2, 1), colors.HexColor("#d97706")),
        ])
    )

    story.append(kpi)
    story.append(Spacer(1, 15))

    story.append(
        Image(
            charts(by_status, by_prio, by_who),
            width=17.5 * cm,
            height=5.1 * cm
        )
    )

    story.append(Spacer(1, 15))

    if not tickets:

        story.append(
            Paragraph(
                "No tickets found during the last 24 hours.",
                styles["Normal"]
            )
        )

    else:

        data = [[
            Paragraph("Ticket", header_cell),
            Paragraph("Title", header_cell),
            Paragraph("Status", header_cell),
            Paragraph("Priority", header_cell),
            Paragraph("Reported", header_cell),
            Paragraph("By", header_cell)
        ]]

        for ticket in tickets:

            ticket_number = str(ticket.get("Ticket Number", ""))
            ticket_title = str(ticket.get("Ticket Title", ""))
            status = str(ticket.get("Status", ""))
            priority = str(ticket.get("Priority", ""))
            reported = str(ticket.get(DATE_COL, ""))
            reporter = str(ticket.get("Reported by", ""))

            data.append([
                Paragraph(html.escape(ticket_number), cell),
                Paragraph(html.escape(ticket_title), cell),
                Paragraph(html.escape(status), cell),
                Paragraph(html.escape(priority), cell),
                Paragraph(html.escape(reported[:10] or "-"), cell),
                Paragraph(html.escape(reporter), cell)
            ])

        table = Table(
            data,
            colWidths=[
                3 * cm,
                5.2 * cm,
                1.8 * cm,
                1.7 * cm,
                2.1 * cm,
                3.7 * cm
            ],
            repeatRows=1
        )

        table_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e1b4b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                colors.white,
                colors.HexColor("#f8fafc")
            ]),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6)
        ]

        for index, ticket in enumerate(tickets, 1):

            status = str(
                ticket.get("Status", "")
            ).strip().lower()

            if status == "solved":

                table_style.extend([
                    ("TEXTCOLOR", (2, index), (2, index), colors.HexColor("#16a34a")),
                    ("FONTNAME", (2, index), (2, index), "Helvetica-Bold")
                ])

            elif status == "pending":

                table_style.extend([
                    ("TEXTCOLOR", (2, index), (2, index), colors.HexColor("#d97706")),
                    ("FONTNAME", (2, index), (2, index), "Helvetica-Bold")
                ])

        table.setStyle(TableStyle(table_style))

        story.append(table)

    document = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm
    )

    document.build(story)

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
