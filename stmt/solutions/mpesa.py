import pdfplumber
from datetime import datetime
import re
import pandas as pd
from typing import Pattern, Union

class MpesaStatementExtractor:
    """
    Extracts transactions from an MPESA PDF statement
    and saves them to a CSV file.

    Usage:
        extractor = MpesaStatementExtractor("../data/MPESA_Statement.pdf", password="543343")
        extractor.run()
    """

    def __init__(self, pdf_path, output_file="mpesa_transaction.csv", password=None):
        self.pdf_path    = pdf_path
        self.output_file = output_file
        self.password    = password
        self.rows        = []   # all rows that will go into the CSV
        self.i           = 0    # row counter

    # =========================================================================
    # HELPERS
    # =========================================================================

    @classmethod
    def clean_num(self, text):
        """Turn a string like '1,000.50' into a float like 1000.5"""
        if not text or str(text).strip() == "":
            return 0.0
        clean = re.sub(r"[^0-9.]", "", str(text))
        try:
            return float(clean)
        except:
            return 0.0

    def format_date(self, date_str):
        """Convert '2026-04-27 13:11:58' into '27/4/2026'"""
        if not date_str:
            return ""
        try:
            date_only = date_str.strip().split(" ")[0]
            date_obj = datetime.strptime(date_only, "%Y-%m-%d")
            return f"{date_obj.day}/{date_obj.month}/{date_obj.year}"
        except:
            return date_str

    def extract(self, pattern: Union[str,Pattern[str]], text:str, flags=0):
        """Find a pattern in text and return the captured group, or '' if not found"""
        match = re.search(pattern, text, flags)
        return match.group(1).strip() if match else ""

    # =========================================================================
    # STEP 1: EXTRACT METADATA FROM PAGE 1
    # =========================================================================

    def extract_metadata(self, page1_text):
        """Read page 1 and return all account info as a dictionary"""
        customer_name    = self.extract(r"Customer Name:\s*(.+)",    page1_text)
        mobile_number    = self.extract(r"Mobile Number:\s*(\d+)",   page1_text)
        email_address    = self.extract(r"Email Address:\s*(\S+)",   page1_text)
        request_date     = self.extract(r"Request Date:\s*(.+)",     page1_text)
        statement_period = self.extract(r"Statement Period:\s*(.+)", page1_text)

        return {
            "customer_name":    customer_name,
            "mobile_number":    mobile_number,
            "email_address":    email_address,
            "request_date":     request_date,
            "statement_period": statement_period,
        }

    # =========================================================================
    # STEP 2: EXTRACT SUMMARY FROM PAGE 1
    # =========================================================================

    def extract_summary(self, page1_text):
        """
        Pull out the summary block (e.g. Send Money, Paybill, etc.)
        and return it as a dictionary of {name: {paid_in, paid_out}}
        """
        summary_block = self.extract(r"SUMMARY(.*?)(TOTAL:.*)", page1_text, re.S)

        pattern = r"([A-Z \-\(\)]+):\s*([\d,]+\.\d{2})\s*([\d,]+\.\d{2})"
        matches = re.findall(pattern, summary_block)

        summary_data = {}
        for name, paid_in, paid_out in matches:
            summary_data[name.strip()] = {"paid_in": paid_in, "paid_out": paid_out}

        return summary_data

    # =========================================================================
    # STEP 3: BUILD HEADER AND METADATA ROWS
    # =========================================================================

    def build_metadata_rows(self, meta, summary_data):
        """Write the header row, metadata rows, and summary rows into self.rows"""

        # First header row
        self.rows.append(["", "TXN_DATE", "VALUE_DATE", "DESCRIPTION", "MONEY_OUT_OR_IN", "BALANCE", "TXN_TYPE"])

        # Put all metadata descriptions in a list then loop through them
        metadata_descriptions = [
            "Customer Name: "    + meta["customer_name"],
            "Mobile Number: "    + meta["mobile_number"],
            "Email Address: "    + meta["email_address"],
            "Statement Period: " + meta["statement_period"],
            "Request Date: "     + meta["request_date"],
        ]

        for description in metadata_descriptions:
            self.rows.append([self.i, "", "", description, "", "", ""])
            self.i += 1

        # Summary rows — one row per summary category
        for name, values in summary_data.items():
            desc = f"{name}: In = {values['paid_in']}, Out = {values['paid_out']}"
            self.rows.append([self.i, "", "", desc, "", "", ""])
            self.i += 1

        # Second header row before transactions
        self.rows.append([self.i, "TXN_DATE", "VALUE_DATE", "DESCRIPTION", "MONEY_OUT_OR_IN", "BALANCE", "TXN_TYPE"])
        self.i += 1

    # =========================================================================
    # STEP 4: EXTRACT TRANSACTIONS FROM ONE PAGE
    # =========================================================================

    def extract_transactions_from_page(self, page):
        """
        Extract all transaction rows from a single PDF page.

        Columns in this PDF:
          row[0] = Receipt No.
          row[1] = Completion Time  ← the date
          row[2] = Details
          row[3] = Transaction Status
          row[4] = Paid In           ← Credit
          row[5] = Withdrawn         ← Debit
          row[6] = Balance
        """
        table = page.extract_table({
            "vertical_strategy":   "lines",
            "horizontal_strategy": "lines"
        })

        if not table:
            return   # no table on this page, nothing to do

        for row in table:
            if not row or len(row) < 7:
                continue

            receipt_no = (row[0] or "").strip()
            comp_time  = (row[1] or "").strip()
            details    = (row[2] or "").strip()
            status     = (row[3] or "").strip()
            paid_in    = self.clean_num(row[4])
            withdrawn  = self.clean_num(row[5])
            balance    = self.clean_num(row[6])

            # Skip header rows — they don't have a date in the date column
            if not re.match(r"\d{4}-\d{2}-\d{2}", comp_time):
                continue

            # Combine Receipt No + Details + Status into one DESCRIPTION field
            desc_parts = [p for p in [receipt_no, details, status] if p]
            description = " | ".join(desc_parts)

            # Work out amount and CR/DR
            if paid_in > 0:
                amount   = paid_in
                txn_type = "CR"
            else:
                amount   = withdrawn
                txn_type = "DR"

            self.rows.append([
                self.i,
                self.format_date(comp_time),   # TXN_DATE
                self.format_date(comp_time),   # VALUE_DATE
                description,
                amount,
                balance,
                txn_type,
            ])
            self.i += 1

    # =========================================================================
    # STEP 5: SAVE TO CSV
    # =========================================================================

    def save(self):
        """Save all rows in self.rows to a CSV file"""
        df = pd.DataFrame(self.rows)
        df.to_csv(self.output_file, index=False, header=False)
        print(f"Done! Extracted {self.i} rows.")
        print(f"Saved to: {self.output_file}")

    # =========================================================================
    # RUN: CALLS ALL STEPS IN ORDER
    # =========================================================================

    def run(self):
        """Main method — runs all steps in order"""
        with pdfplumber.open(self.pdf_path, password=self.password) as pdf:

            # Step 1 & 2: read page 1 and extract metadata + summary
            page1_text   = pdf.pages[0].extract_text() or ""
            meta         = self.extract_metadata(page1_text)
            summary_data = self.extract_summary(page1_text)

            # Step 3: write metadata and summary into self.rows
            self.build_metadata_rows(meta, summary_data)

            # Step 4: loop every page and extract transactions
            for page in pdf.pages:
                self.extract_transactions_from_page(page)

        # Step 5: save everything to CSV
        self.save()


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    extractor = MpesaStatementExtractor(
        pdf_path    = "../data/MPESA_Statement.pdf",
        output_file = "mpesa_transaction.csv",
        password    = "543343"
    )
    extractor.run()