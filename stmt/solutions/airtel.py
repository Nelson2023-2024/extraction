import pdfplumber
from datetime import datetime
import re
import pandas as pd


class AirtelStatementExtractor:
    """
    Extracts transactions from an Airtel Money PDF statement
    and saves them to a CSV file.

    Usage:
        extractor = AirtelStatementExtractor("../data/Airtel Money Statement.pdf")
        extractor.run()
    """

    def __init__(self, pdf_path, output_file="airtel_transactions.csv"):
        self.pdf_path    = pdf_path
        self.output_file = output_file
        self.rows        = []    # all rows that will go into the CSV
        self.current_idx = 0     # row counter for transactions

    # =========================================================================
    # HELPERS
    # =========================================================================

    def clean_num(self, text):
        """Turn a string like '1,000.50' or '--' into a float like 1000.5"""
        if not text or str(text).strip() in ["", "--"]:
            return 0.0
        clean = re.sub(r"[^0-9.]", "", str(text))
        try:
            return float(clean)
        except:
            return 0.0

    def format_date(self, date_str):
        """Convert '09/02/26' into '9/2/2026'"""
        if not date_str:
            return ""
        try:
            date_obj = datetime.strptime(date_str.strip(), "%d/%m/%y")
            return f"{date_obj.day}/{date_obj.month}/{date_obj.year}"
        except:
            return date_str

    def extract(self, pattern, text, flags=0):
        """Search for a pattern in text and return the captured group, or '' if not found"""
        match = re.search(pattern, text, flags)
        return match.group(1).strip() if match else ""

    # =========================================================================
    # STEP 1: EXTRACT METADATA FROM PAGE 1
    # =========================================================================

    def extract_metadata(self, page1_text):
        """
        Reads the first page text and pulls out all the account info.
        Returns a dictionary with all the metadata values.
        """
        lines = page1_text.split("\n")

        # The first line on page 1 is always the customer name
        customer_name = lines[0].strip() if lines else ""

        # Find account reference number (digits after the word "period")
        account_ref = self.extract(r"period\s+(\d+)", page1_text)

        # Find the date range e.g. "01 Jan 2026 to 28 Feb 2026"
        date_range = self.extract(
            r"(\d{2} [A-Z][a-z]{2} \d{4} to \d{2} [A-Z][a-z]{2} \d{4})",
            page1_text
        )

        if " to " in date_range:
            report_from, report_to = date_range.split(" to ")
        else:
            report_from, report_to = "", ""

        # Pull out the four summary numbers
        opening_bal  = self.clean_num(self.extract(r"Opening Balance\s*([\d,.]+)",      page1_text))
        closing_bal  = self.clean_num(self.extract(r"Closing Balance\s*([\d,.]+)",      page1_text))
        total_credit = self.clean_num(self.extract(r"Total Money Credited\s*([\d,.]+)", page1_text))
        total_debit  = self.clean_num(self.extract(r"Total Money Debited\s*([\d,.]+)",  page1_text))

        # Return everything as a dictionary so other methods can use it
        return {
            "customer_name": customer_name,
            "account_ref":   account_ref,
            "report_from":   report_from,
            "report_to":     report_to,
            "opening_bal":   opening_bal,
            "closing_bal":   closing_bal,
            "total_credit":  total_credit,
            "total_debit":   total_debit,
        }

    # =========================================================================
    # STEP 2: WRITE HEADER AND METADATA ROWS INTO self.rows
    # =========================================================================

    def build_metadata_rows(self, meta):
        """
        Takes the metadata dictionary and writes it into self.rows
        in the correct CSV format.
        """
        # First header row (column names)
        self.rows.append(["", "TXN_DATE", "VALUE_DATE", "DESCRIPTION", "MONEY_OUT_OR_IN", "BALANCE", "TXN_TYPE"])

        # Put all metadata descriptions in a list
        metadata_descriptions = [
            "AccountType: Airtel Money",
            "Customer Name: "   + meta["customer_name"],
            "Account Number: "  + meta["account_ref"],
            "Report From: "     + meta["report_from"],
            "Report To: "       + meta["report_to"],
            "Opening Balance: " + str(meta["opening_bal"]),
            "Closing Balance: " + str(meta["closing_bal"]),
            "Total Credit: "    + str(meta["total_credit"]),
            "Total Debit: "     + str(meta["total_debit"]),
            "Currency: ZMW",
        ]

        # Loop through the list and append each one as a row
        i = 0
        for description in metadata_descriptions:
            self.rows.append([i, "", "", description, "", "", ""])
            i += 1

        # Second header row (repeated before transactions start)
        self.rows.append([i, "TXN_DATE", "VALUE_DATE", "DESCRIPTION", "MONEY_OUT_OR_IN", "BALANCE", "TXN_TYPE"])

        # Transactions will start from the next index
        self.current_idx = i + 1

    # =========================================================================
    # STEP 3: EXTRACT TRANSACTIONS FROM ONE PAGE
    # =========================================================================

    def extract_transactions_from_page(self, page):
        """
        Takes a single PDF page, reads all its lines, and picks out
        transaction rows using a regex pattern.

        Each transaction in this PDF spans TWO lines:
          Line 1: 08/02/26   Money Sent to Emmanuel   8,650   --   55,124.531
          Line 2: 20:20 PM (PP260208.2020.Z75655)
        """
        text  = page.extract_text() or ""
        lines = text.split("\n")

        for idx, line in enumerate(lines):

            # Try to match a transaction line (starts with a date)
            match = re.match(
                r"(\d{2}/\d{2}/\d{2})\s+(.+?)\s+([\d,.-]+|--)\s+([\d,.-]+|--)\s+([\d,.]+)",
                line
            )

            if not match:
                continue   # not a transaction line, skip it

            raw_date = match.group(1)   # "08/02/26"
            details  = match.group(2)   # "Money Sent to Emmanuel kambunga"
            credited = match.group(3)   # "8,650" or "--"
            debited  = match.group(4)   # "--" or "1,156"
            balance  = match.group(5)   # "55,124.531"

            # Check if the next line has the time and reference number
            full_desc = details
            if idx + 1 < len(lines):
                next_line = lines[idx + 1].strip()
                if re.search(r"\d{2}:\d{2}\s*(AM|PM)", next_line):
                    full_desc = details + " " + next_line

            # Work out amount and CR/DR
            credit_amount = self.clean_num(credited)
            debit_amount  = self.clean_num(debited)

            if credit_amount > 0:
                amount   = credit_amount
                txn_type = "CR"
            else:
                amount   = debit_amount
                txn_type = "DR"

            self.rows.append([
                self.current_idx,
                self.format_date(raw_date),   # TXN_DATE
                self.format_date(raw_date),   # VALUE_DATE
                full_desc,
                amount,
                self.clean_num(balance),
                txn_type
            ])
            self.current_idx += 1

    # =========================================================================
    # STEP 4: SAVE self.rows TO CSV
    # =========================================================================

    def save(self):
        """Save all rows collected in self.rows to a CSV file."""
        df = pd.DataFrame(self.rows)
        df.to_csv(self.output_file, index=False, header=False)
        print(f"Done! Extracted {self.current_idx} transactions.")
        print(f"Saved to: {self.output_file}")

    # =========================================================================
    # RUN: CALLS ALL STEPS IN ORDER
    # =========================================================================

    def run(self):
        """
        Main method - runs all steps in order:
        1. Open PDF
        2. Extract metadata from page 1
        3. Build metadata rows
        4. Loop through all pages and extract transactions
        5. Save to CSV
        """
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
# ENTRY POINT — this runs when you execute the script
# =============================================================================
if __name__ == "__main__":
    extractor = AirtelStatementExtractor(
        pdf_path    = "../data/Airtel Money Statement.pdf",
        output_file = "airtel_transactions.csv"
    )
    extractor.run()