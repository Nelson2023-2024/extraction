import pdfplumber
from datetime import datetime
import re
import pandas as pd

# --- CONFIGURATION ---
pdf_path = "../data/Zmk_Statement.pdf"
output_file = "zmk_transactions.csv"

# ── Helper: convert "20-12-25 11:31 AM " → "2/1/2026" ───────────────────────────────
def format_date(date_str):
    if not date_str:
        return ""

    try:
        date_only = re.sub(r"\s+\d{1,2}:\d{2}\s*(AM|PM)?", "", date_str.strip())
        date_obj = datetime.strptime(date_only, "%d-%m-%y")
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

# ── Helper: check if a cell looks like a date e.g. "20-12-25 11:31 AM " ───────
def is_date(text):
    if not text:
        return False
    return bool(
        re.match(r"\d{2}-\d{2}-\d{2}(\s+\d{1,2}:\d{2}\s*(AM|PM)?)?", str(text).strip())
    )

# ── Helper: search for a pattern, return group(1) or "" if not found ──────────
def extract(pattern, text, flags=0):
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else ""

rows = []

with pdfplumber.open(pdf_path) as pdf:
    # ── 1. READ PAGE 1 TEXT ───────────────────────────────────────────────────
    page1_text = pdf.pages[0].extract_text() or ""
    last_page_text = pdf.pages[-1].extract_text() or ""
    print(page1_text)

    # ── 2. EXTRACT PAGE 1 METADATA ───────────────────────────────────────────
    customer_name = extract(r"Customer Name:\s*(.+)", page1_text)
    mobile_number = extract(r"Mobile Number:\s*(\d+)", page1_text)
    email_address = extract(r"Email Address:\s*(\S+)", page1_text)
    
    report_period = extract(r"Statement Period:\s*(.+)", page1_text)
    if " to " in report_period:
        report_from, report_to = report_period.split(" to ")
    else:
        report_from, report_to = "", ""
    
    opening_bal = extract(r"Opening Balance:\s*Zmk\s*([\d,.]+)", page1_text)
    closing_bal = extract(r"Closing Balance:\s*Zmk\s*([\d,.]+)", page1_text)
    total_credit = extract(r"Total Credit:\s*Zmk\s*([\d,.]+)", page1_text)
    total_debit = extract(r"Total Debit:\s*Zmk\s*([\d,.]+)", page1_text)
    request_date = extract(r"Request Date:\s*(.+)", page1_text)


    # ── 3. COLUMN HEADER ROW (col A is empty on purpose) ─────────────────────
    rows.append(["", "TXN_DATE", "VALUE_DATE", "DESCRIPTION", "MONEY_OUT_OR_IN", "BALANCE", "TXN_TYPE"])

    # ── 4. METADATA ROWS — exact field names from the PDF ────────────────────
    rows.append([0, "", "", f"Customer Name: {customer_name}", "", "", ""])
    rows.append([1, "", "", f"Mobile Number: {mobile_number}", "", "", ""])
    rows.append([2, "", "", f"Email Address: {email_address}", "", "", ""])
    rows.append([3, "", "", f"Report From: {report_from}", "", "", ""])
    rows.append([4, "", "", f"Report To: {report_to}", "", "", ""])
    rows.append([5, "", "", f"Opening Balance: {clean_num(opening_bal)}", "", "", ""])
    rows.append([6, "", "", f"Closing Balance: {clean_num(closing_bal)}", "", "", ""])
    rows.append([7, "", "", f"Total Credit: {clean_num(total_credit)}", "", "", ""])
    rows.append([8, "", "", f"Total Debit: {clean_num(total_debit)}", "", "", ""])
    rows.append([9, "", "", f"Request Date: {request_date}", "", "", ""])

    # ── 5. SECOND HEADER ROW ─────────────────────────────────────────────────
    rows.append([10, "TXN_DATE", "VALUE_DATE", "DESCRIPTION", "MONEY_OUT_OR_IN", "BALANCE", "TXN_TYPE"])

    ## ── 6. EXTRACT TRANSACTIONS PAGE BY PAGE ─────────────────────────────────
    current_idx = 11

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

            # Columns: [Transaction ID, Transaction Date, Description, Status, Transaction Amount, Credit/Debit, Balance]
            txn_id      = (row[0] or "").strip()
            txn_date    = (row[1] or "").strip()
            description = (row[2] or "").strip()
            status      = (row[3] or "").strip()
            amount_raw  = (row[4] or "").strip()
            cr_dr       = (row[5] or "").strip().upper()
            balance_raw = (row[6] or "").strip()

            # Skip header rows or empty rows
            if not is_date(txn_date):
                continue

            # Combine Transaction ID + Description + Status into one DESCRIPTION field
            desc_parts = [part for part in [txn_id, description, status] if part]
            desc = " | ".join(desc_parts)
            desc = " ".join(desc.split())  # Collapse extra whitespace

            amount = clean_num(amount_raw)
            balance = clean_num(balance_raw)

            # Determine TXN_TYPE from Credit/Debit column
            if "CREDIT" in cr_dr:
                txn_type = "CR"
            elif "DEBIT" in cr_dr:
                txn_type = "DR"
            else:
                txn_type = cr_dr  # Fallback: use whatever is there

            rows.append([
                current_idx,
                format_date(txn_date),
                format_date(txn_date),   # VALUE_DATE — same as TXN_DATE; adjust if PDF has a separate column
                desc,
                amount,
                balance,
                txn_type
            ])
            current_idx += 1

# ── 7. SAVE TO CSV ───────────────────────────────────────────────────────────
df = pd.DataFrame(rows[1:], columns=rows[0])  # Skip the first empty row
df.to_csv(output_file, index=False)
