import pdfplumber
from datetime import datetime
import re
import pandas as pd

# --- CONFIGURATION ---
pdf_path = "../data/MPESA_Statement.pdf"
output_file = "mpesa_transaction.csv"


# ── Helper: convert "2026-04-27 13:11:58" → "27/4/2026" ──────────────────────
def format_date(date_str):
    if not date_str:
        return ""
    try:
        # 1. Take only the first part (the date)
        date_only = date_str.strip().split(" ")[0]
        # 2. Parse Year-Month-Day
        date_obj = datetime.strptime(date_only, "%Y-%m-%d")
        # 3. Return Day/Month/Year
        return f"{date_obj.day}/{date_obj.month}/{date_obj.year}"
    except:
        return date_str


# ── Helper: strip commas and convert to float ─────────────────────────────────
def clean_num(text):
    if not text or str(text).strip() == "":
        return 0.0
    clean = re.sub(r"[^0-9.]", "", str(text))
    try:
        return float(clean)
    except:
        return 0.0


# ── Helper: search for a pattern, return group(1) or "" if not found ──────────
def extract(pattern, text, flags=0):
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else ""


rows = []
with pdfplumber.open(pdf_path, password="543343") as pdf:
    # Read Page 1 Text
    page1_text = pdf.pages[0].extract_text() or ""

    print(page1_text)

    # ── 1. EXTRACT HEADER METADATA ───────────────────────────────────────────
    customer_name = extract(r"Customer Name:\s*(.+)", page1_text)
    mobile_number = extract(r"Mobile Number:\s*(\d+)", page1_text)
    email_address = extract(r"Email Address:\s*(\S+)", page1_text)
    request_date = extract(r"Request Date:\s*(.+)", page1_text)
    statement_period = extract(r"Statement Period:\s*(.+)", page1_text)

    # ── 2. EXTRACT SUMMARY ───────────────────────────────────────
    summary_block = extract(r"SUMMARY(.*?)(TOTAL:.*)", page1_text, re.S)

    pattern = r"([A-Z \-\(\)]+):\s*([\d,]+\.\d{2})\s*([\d,]+\.\d{2})"
    matches = re.findall(pattern, summary_block)

    summary_data = {}
    for name, paid_in, paid_out in matches:
        summary_data[name.strip()] = {"paid_in": paid_in, "paid_out": paid_out}

    # ── PRINT ───────────────────────────────────────────────────
    print("\n--- SUMMARY ---")
    for k, v in summary_data.items():
        print(f"{k}: In = {v['paid_in']}, Out = {v['paid_out']}")

    # ── 3. PRINTING THE RESULTS ──────────────────────────────────────────────
    print("--- METADATA ---")
    print(f"Customer Name:   {customer_name}")
    print(f"Mobile Number:   {mobile_number}")
    print(f"Email Address:   {email_address}")
    print(f"Request Date:  {request_date}")
    print(f"Statement Period: {statement_period}")

    # ── 3. COLUMN HEADER ROW (col A is empty on purpose) ─────────────────────
    rows.append(
        [
            "",
            "TXN_DATE",
            "VALUE_DATE",
            "DESCRIPTION",
            "MONEY_OUT_OR_IN",
            "BALANCE",
            "TXN_TYPE",
        ]
    )

    # ── 4. METADATA ROWS ───────────────────────────────────────
    i = 0

    rows.append([i, "", "", f"Customer Name: {customer_name}", "", "", ""])
    i += 1
    rows.append([i, "", "", f"Mobile Number: {mobile_number}", "", "", ""])
    i += 1
    rows.append([i, "", "", f"Email Address: {email_address}", "", "", ""])
    i += 1
    rows.append([i, "", "", f"Statement Period: {statement_period}", "", "", ""])
    i += 1
    rows.append([i, "", "", f"Request Date: {request_date}", "", "", ""])
    i += 1
    # ── 5. SUMMARY ROWS ───────────────────────────────────────
    for name, values in summary_data.items():
        desc = f"{name}: In = {values['paid_in']}, Out = {values['paid_out']}"
        rows.append([i, "", "", desc, "", "", ""])
        i += 1
    # ── 6. SECOND HEADER ROW ──────────────────────────────────
    rows.append(
        [
            i,
            "TXN_DATE",
            "VALUE_DATE",
            "DESCRIPTION",
            "MONEY_OUT_OR_IN",
            "BALANCE",
            "TXN_TYPE",
        ]
    )
    # ── 7. EXTRACT TRANSACTIONS PAGE BY PAGE ─────────────────────────────────
    i += 1  # continue index after metadata rows

    for page in pdf.pages:
        table = page.extract_table({
            "vertical_strategy":   "lines",
            "horizontal_strategy": "lines"
        })
        if not table:
            continue

        for row in table:
            if not row or len(row) < 7:
                continue

            # Columns: [Receipt No., Completion Time, Details, Transaction Status, Paid In, Withdrawn, Balance]
            receipt_no  = (row[0] or "").strip()
            comp_time   = (row[1] or "").strip()
            details     = (row[2] or "").strip()
            status      = (row[3] or "").strip()
            paid_in     = clean_num(row[4])
            withdrawn   = clean_num(row[5])
            balance     = clean_num(row[6])

            # Skip header rows
            if not re.match(r"\d{4}-\d{2}-\d{2}", comp_time):
                continue

            # Combine Receipt No + Details + Status into DESCRIPTION
            desc_parts = [p for p in [receipt_no, details, status] if p]
            desc = " | ".join(desc_parts)

            # Determine amount and TXN_TYPE
            # Withdrawn values in PDF appear as negatives e.g. -1300.00
            if paid_in > 0:
                amount   = paid_in
                txn_type = "CR"
            else:
                amount   = withdrawn  # already positive after clean_num strips the minus
                txn_type = "DR"

            rows.append([
                i,
                format_date(comp_time),   # TXN_DATE
                format_date(comp_time),   # VALUE_DATE (same column in this PDF)
                desc,
                amount,
                balance,
                txn_type,
            ])
            i += 1

# ── 8. SAVE ───────────────────────────────────────────────────────────────────
df = pd.DataFrame(rows)
df.to_csv(output_file, index=False, header=False)
print(f"Done — {i} rows written to {output_file}")
