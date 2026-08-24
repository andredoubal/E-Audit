"""What arrived, read for what it is rather than for what it is called.

Until this package existed the application decided what a spreadsheet *was* by looking at its
filename — `document_like("sales", "revenue", "output")`. That works on a case whose files are
named the way the demo names them and fails silently everywhere else: a purchases register
called `Q1_analysis.xlsx` is invisible, and a trial balance called `sales_tb.xlsx` is read as
a sales listing and totalled into the output box.

Profiling replaces the guess with a reading of the file's own contents — which columns are
present, what they hold, how the values behave — and publishes the result with a confidence and
a stated reason, so an auditor can see why the system thinks a file is what it thinks it is,
and correct it when it is wrong.
"""
