#!/usr/bin/env python3
import sys

def main():
    print("=== ASSIGNMENT: ERRORING GRADER ===")
    # Intentional failure to simulate a grader that errors out
    raise RuntimeError("Intentional grader failure for testing")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Print stack trace and exit non-zero
        raise
