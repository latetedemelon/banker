#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""Entry point for the bankhub CLI.

Kept at the repository root so existing tooling (``python main.py ...`` and
the Docker image) keeps working.  All commands -- new and legacy -- live in
:mod:`bankhub.cli`.
"""

from bankhub.cli import main

if __name__ == "__main__":
    main()
