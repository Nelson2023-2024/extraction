import pdfplumber
from datetime import datetime
import re
import pandas as pd


class ZmkStatementExtractor:
    """
    Extracts transactions from a ZMK PDF statement
    and saves them to a CSV file.

    Usage:
        extractor = ZmkStatementExtractor("../data/Zmk_Statement.pdf")
        extractor.run()
    """

    def __init__(self, pdf_path, output_file="zmk_transactions.csv"):
        self.pdf_path = pdf_path
        self.output_file = output_file
        self.rows = []  # all rows that will go into the CSV
        self.i = 0  # row counter

    # =========================================================================
    # HELPERS
    # =========================================================================

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
        """Convert '20-12-25 11:31 AM' into '20/12/2025'"""
        if not date_str:
            return ""
        try:
            date_only = re.sub(r"\s+\d{1,2}:\d{2}\s*(AM|PM)?", "", date_str.strip())
            date_obj = datetime.strptime(date_only, "%d-%m-%y")
            return f"{date_obj.day}/{date_obj.month}/{date_obj.year}"
        except:
            return date_str

    def is_date(self, text):
        """Check if text looks like a date e.g. '20-12-25 11:31 AM'"""
        if not text:
            return False
        return bool(re.match(r"\d{2}-\d{2}-\d{2}", str(text).strip()))

    def extract(self, pattern, text, flags=0):
        """Find a pattern in text and return the captured group, or '' if not found"""
        match = re.search(pattern, text, flags)
        return match.group(1).strip() if match else ""

    # =========================================================================
    # STEP 1: EXTRACT METADATA FROM PAGE 1
    # =========================================================================

    def extract_metadata(self, page1_text):
        """Read page 1 and return all account info as a dictionary"""
        customer_name = self.extract(r"Customer Name:\s*(.+)", page1_text)
        mobile_number = self.extract(r"Mobile Number:\s*(\d+)", page1_text)
        email_address = self.extract(r"Email Address:\s*(\S+)", page1_text)
        request_date = self.extract(r"Request Date:\s*(.+)", page1_text)
        report_period = self.extract(r"Statement Period:\s*(.+)", page1_text)
        opening_bal = self.extract(r"Opening Balance:\s*Zmk\s*([\d,.]+)", page1_text)
        closing_bal = self.extract(r"Closing Balance:\s*Zmk\s*([\d,.]+)", page1_text)
        total_credit = self.extract(r"Total Credit:\s*Zmk\s*([\d,.]+)", page1_text)
        total_debit = self.extract(r"Total Debit:\s*Zmk\s*([\d,.]+)", page1_text)

        if " to " in report_period:
            report_from, report_to = report_period.split(" to ")
        else:
            report_from, report_to = "", ""

        return {
            "customer_name": customer_name,
            "mobile_number": mobile_number,
            "email_address": email_address,
            "request_date": request_date,
            "report_from": report_from,
            "report_to": report_to,
            "opening_bal": self.clean_num(opening_bal),
            "closing_bal": self.clean_num(closing_bal),
            "total_credit": self.clean_num(total_credit),
            "total_debit": self.clean_num(total_debit),
        }

    # =========================================================================
    # STEP 2: BUILD HEADER AND METADATA ROWS
    # =========================================================================

    def build_metadata_rows(self, meta):
        """Write the header row and metadata rows into self.rows"""

        # First header row
        self.rows.append(
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

        # Put all metadata descriptions in a list then loop through them
        metadata_descriptions = [
            "Customer Name: " + meta["customer_name"],
            "Mobile Number: " + meta["mobile_number"],
            "Email Address: " + meta["email_address"],
            "Report From: " + meta["report_from"],
            "Report To: " + meta["report_to"],
            "Opening Balance: " + str(meta["opening_bal"]),
            "Closing Balance: " + str(meta["closing_bal"]),
            "Total Credit: " + str(meta["total_credit"]),
            "Total Debit: " + str(meta["total_debit"]),
            "Request Date: " + meta["request_date"],
        ]

        for description in metadata_descriptions:
            self.rows.append([self.i, "", "", description, "", "", ""])
            self.i += 1

        # Second header row before transactions
        self.rows.append(
            [
                self.i,
                "TXN_DATE",
                "VALUE_DATE",
                "DESCRIPTION",
                "MONEY_OUT_OR_IN",
                "BALANCE",
                "TXN_TYPE",
            ]
        )
        self.i += 1

    # =========================================================================
    # STEP 3: EXTRACT TRANSACTIONS FROM ONE PAGE
    # =========================================================================

    def extract_transactions_from_page(self, page):
        """
        Extract all transaction rows from a single PDF page.

        Columns in this PDF:
          row[0] = Transaction ID
          row[1] = Transaction Date  <- the date
          row[2] = Description
          row[3] = Status
          row[4] = Transaction Amount
          row[5] = Credit/Debit
          row[6] = Balance
        """
        table = page.extract_table(
            {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
        )

        if not table:
            return  # no table on this page, nothing to do

        for row in table:
            if not row or len(row) < 7:
                continue

            txn_id = (row[0] or "").strip()
            txn_date = (row[1] or "").strip()
            description = (row[2] or "").strip()
            status = (row[3] or "").strip()
            amount_raw = (row[4] or "").strip()
            cr_dr = (row[5] or "").strip().upper()
            balance_raw = (row[6] or "").strip()

            # Skip header rows - they don't have a date in the date column
            if not self.is_date(txn_date):
                continue

            # Combine Transaction ID + Description + Status into one DESCRIPTION field
            desc_parts = [part for part in [txn_id, description, status] if part]
            desc = " | ".join(desc_parts)
            desc = " ".join(desc.split())  # remove extra whitespace

            amount = self.clean_num(amount_raw)
            balance = self.clean_num(balance_raw)

            # Determine CR or DR from the Credit/Debit column
            if "CREDIT" in cr_dr:
                txn_type = "CR"
            elif "DEBIT" in cr_dr:
                txn_type = "DR"
            else:
                txn_type = cr_dr  # fallback: use whatever is there

            self.rows.append(
                [
                    self.i,
                    self.format_date(txn_date),  # TXN_DATE
                    self.format_date(txn_date),  # VALUE_DATE
                    desc,
                    amount,
                    balance,
                    txn_type,
                ]
            )
            self.i += 1

    # =========================================================================
    # STEP 4: SAVE TO CSV
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
        """Main method - runs all steps in order"""
        with pdfplumber.open(self.pdf_path) as pdf:

            # Step 1: read metadata from page 1
            page1_text = pdf.pages[0].extract_text() or ""
            meta = self.extract_metadata(page1_text)

            # Step 2: write metadata into self.rows
            self.build_metadata_rows(meta)

            # Step 3: loop every page and extract transactions
            for page in pdf.pages:
                self.extract_transactions_from_page(page)

        # Step 4: save everything to CSV
        self.save()


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    extractor = ZmkStatementExtractor(
        pdf_path="../data/Zmk_Statement.pdf", output_file="zmk_transactions.csv"
    )
    extractor.run()
