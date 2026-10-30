"""
The ``--help`` texts of ``summary`` and ``verdict``, recorded before spec 009.

Spec 009 split the shared parent parser (ADR-7). A test compares the live text with these, byte for
byte, at 80 columns: the split must not change what an existing command prints. The text is the
same on Python 3.12 and 3.15.
"""

from __future__ import annotations

# Recorded before the parent parser was split; test_cli_fetch compares it byte for byte.
SUMMARY_HELP = (
    "usage: mailvigil summary [-h] [--config FILE] [--domain DOMAIN] [--json]\n"
    "                         [--lang {en,pt-BR}]\n"
    "                         PATH [PATH ...]\n"
    "\n"
    "Sum up DMARC aggregate reports per sender and per situation.\n"
    "\n"
    "positional arguments:\n"
    "  PATH               report files (.xml .gz .zip), mail files (.eml .mbox) or\n"
    "                     folders of them\n"
    "\n"
    "options:\n"
    "  -h, --help         show this help message and exit\n"
    "  --config FILE      TOML file with the domain and the selector map (default:\n"
    "                     mailvigil.toml in the current folder, if there is one)\n"
    "  --domain DOMAIN    the domain the reports are about (required when there is\n"
    "                     no configuration file)\n"
    "  --json             print one JSON document instead of the text (see\n"
    "                     docs/json-schema.md)\n"
    "  --lang {en,pt-BR}  language of the text and of the refusal lines (default:\n"
    "                     en); the JSON has none\n"
)

# Same as above, for the command that also has --html.
VERDICT_HELP = (
    "usage: mailvigil verdict [-h] [--config FILE] [--domain DOMAIN] [--json]\n"
    "                         [--lang {en,pt-BR}] [--html] [--output FILE]\n"
    "                         PATH [PATH ...]\n"
    "\n"
    "Say if the domain is ready for p=reject, from DMARC aggregate reports. The\n"
    "exit code is 0 for ready, 3 for too early and 4 for not ready.\n"
    "\n"
    "positional arguments:\n"
    "  PATH               report files (.xml .gz .zip), mail files (.eml .mbox) or\n"
    "                     folders of them\n"
    "\n"
    "options:\n"
    "  -h, --help         show this help message and exit\n"
    "  --config FILE      TOML file with the domain and the selector map (default:\n"
    "                     mailvigil.toml in the current folder, if there is one)\n"
    "  --domain DOMAIN    the domain the reports are about (required when there is\n"
    "                     no configuration file)\n"
    "  --json             print one JSON document instead of the text (see\n"
    "                     docs/json-schema.md)\n"
    "  --lang {en,pt-BR}  language of the text and of the refusal lines (default:\n"
    "                     en); the JSON has none\n"
    "  --html             print one self-contained HTML page instead of the text;\n"
    "                     redirect it to a file (mailvigil verdict ... --html >\n"
    "                     report.html) or write it with --output; not with --json\n"
    "  --output FILE      write the --html page to FILE as ASCII, replacing it,\n"
    "                     instead of printing it (use it in Windows PowerShell 5.1,\n"
    "                     whose > writes UTF-16); requires --html\n"
)
