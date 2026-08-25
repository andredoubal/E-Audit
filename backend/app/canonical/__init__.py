"""One shape every dataset is read into, and the lineage back to where each value came from.

Reconciliation used to read a role straight off a profiled spreadsheet — the VAT column here,
the date column there — which works for one comparison at a time and falls apart the moment
three sources have to be set against each other at invoice level, by VAT treatment, with a
drill-down to the original row. Each comparison was re-deriving the same facts from raw columns
in its own way.

The canonical record fixes the shape once. A sales register row, a purchase register row and a
line of the Authority's e-invoice extract all become the same object, carrying the same fields,
with `source_file` and `source_row` on every one of them. Everything downstream — the six
pairwise comparisons, the VAT-treatment breakdown, the transaction matching, the exceptions, and
ultimately a finding in the audit report — is built from these and can therefore be walked back
to the cell it came from.

**Absent is not zero.** Every monetary and identifying field is optional, and a record says
which fields it could not read rather than defaulting them. That distinction is the difference
between "this taxpayer declared nothing" and "we were not given the column", and the whole
reconciliation layer is written to keep them apart.
"""
