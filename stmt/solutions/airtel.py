import pdfplumber
from datetime import datetime
import re
import pandas as pd

# --- CONFIGURATION ---
pdf_path = "../data/Airtel Money Statement.pdf"
output_file = "airtel_transactions.csv"


# ── Helpers ──────────────────────────────────────────────────────────────────
def clean_num(text):
    if not text or str(text).strip() in ["", "--"]:
        return 0.0
    clean = re.sub(r"[^0-9.]", "", str(text))
    try:
        return float(clean)
    except:
        return 0.0


def format_date(date_str):
    if not date_str:
        return ""
    try:
        # Airtel format is 09/02/26
        date_obj = datetime.strptime(date_str.strip(), "%d/%m/%y")
        return f"{date_obj.day}/{date_obj.month}/{date_obj.year}"
    except:
        return date_str


def extract(pattern, text, flags=0):
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else ""


rows = []

with pdfplumber.open(pdf_path) as pdf:
    # ── 1. METADATA EXTRACTION (Page 1) ──────────────────────────────────────
    first_page_text = pdf.pages[0].extract_text() or ""
    lines_p1 = first_page_text.split("\n")

    customer_name = lines_p1[0].strip() if lines_p1 else ""
    account_ref = extract(r"period\s+(\d+)", first_page_text)
    date_range = extract(
        r"(\d{2} [A-Z][a-z]{2} \d{4} to \d{2} [A-Z][a-z]{2} \d{4})", first_page_text
    )

    if " to " in date_range:
        report_from, report_to = date_range.split(" to ")
    else:
        report_from, report_to = "", ""

    # Summary Numbers
    summary_keys = {
        "Total Money Debited": "Total Debit",
        "Total Money Credited": "Total Credit",
        "Opening Balance": "Opening Balance",
        "Closing Balance": "Closing Balance",
    }
    summary_values = {}
    for key, label in summary_keys.items():
        summary_values[label] = clean_num(
            extract(rf"{key}\s*([\d,.]+)", first_page_text)
        )

    # ── 2. BUILD HEADER & METADATA ROWS ──────────────────────────────────────
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

    i = 0
    metadata_items = [
        f"AccountType: Airtel Money",
        f"Customer Name: {customer_name}",
        f"Account Number: {account_ref}",
        f"Report From: {report_from}",
        f"Report To: {report_to}",
        f"Opening Balance: {summary_values['Opening Balance']}",
        f"Closing Balance: {summary_values['Closing Balance']}",
        f"Total Credit: {summary_values['Total Credit']}",
        f"Total Debit: {summary_values['Total Debit']}",
        f"Currency: ZMW",
    ]

    for item in metadata_items:
        rows.append([i, "", "", item, "", "", ""])
        i += 1

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
    current_idx = i + 1

    # ── 3. TRANSACTION EXTRACTION (All Pages) ────────────────────────────────
    for page in pdf.pages:
        text = page.extract_text() or ""
        lines = text.split("\n")
        print(text)

        for idx, line in enumerate(lines):
            # Regex to find the start of a transaction: Date (09/02/26)
            match = re.match(
                r"(\d{2}/\d{2}/\d{2})\s+(.+?)\s+([\d,.-]+|--)\s+([\d,.-]+|--)\s+([\d,.]+)",
                line,
            )

            if match:
                raw_date, details, credited, debited, balance = match.groups()

                # Format the date
                clean_date = format_date(raw_date)

                # Check for second line (Time and Ref)
                # Usually the very next line looks like: "15:46 PM (PP...)"
                full_desc = details
                if idx + 1 < len(lines) and re.search(
                    r"\d{2}:\d{2}\s+(AM|PM)", lines[idx + 1]
                ):
                    full_desc += " " + lines[idx + 1].strip()

                # Determine CR/DR
                c_val = clean_num(credited)
                d_val = clean_num(debited)

                if c_val > 0:
                    amount, txn_type = c_val, "CR"
                else:
                    amount, txn_type = d_val, "DR"

                # CLEAN THE BALANCE HERE
                # We use clean_num to remove the commas, then round to 2 decimal places
                clean_balance = clean_num(balance)

                rows.append(
                    [
                        current_idx,
                        clean_date,
                        clean_date,
                        full_desc,
                        amount,
                        clean_balance,
                        txn_type,
                    ]
                )
                current_idx += 1

# ── 4. SAVE ──────────────────────────────────────────────────────────────────
df = pd.DataFrame(rows)
df.to_csv(output_file, index=False, header=False)
print(f"Done! Created {output_file} with {current_idx} rows.")
